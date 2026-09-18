"""Relay between one browser call and one Higgs Realtime session.

Browser -> gateway: binary frames are PCM16 24 kHz mic audio; text frames are
JSON control messages ({"type": "flushed", ...}).
Gateway -> browser: binary frames are Patrick's PCM16 24 kHz audio; text frames
are JSON events for the UI (transcripts, tool calls, flush requests).

The Boson key stays here. Tool calls are executed here, never in the browser.
"""
import asyncio
import base64
import json
import logging
import os
import time

import websockets
from fastapi import WebSocket, WebSocketDisconnect

import insforge
import patrick
from redact import redact

log = logging.getLogger("relay")
BOSON_URL = "wss://api.boson.ai/v1/realtime?model=higgs-realtime"


class CallSession:
    def __init__(self, browser: WebSocket, tools: list[dict], handlers: dict):
        self.browser = browser
        self.tools = tools
        self.handlers = handlers  # tool name -> async fn(session, **args) -> str|dict
        self.boson = None
        self.case_id = None
        self.case_type = None
        self.fields: dict[str, str] = {}          # case file cache
        self.turns: dict[str, dict] = {}          # item_id -> transcript turn, in order
        self.scribes: dict[str, asyncio.Task] = {}
        self.searched_roles: set[str] = set()
        self.authorities: dict[str, dict] = {}    # role -> authorities row
        self.searching = 0
        self.asked_for: set[str] = set()         # form fields Patrick was already told to ask about
        self.emergency = False
        self.last_caller_text_at = 0.0
        self.summary = ""
        self.proposed_at_turn = None             # set by propose_filing; file_case refuses without it
        self.filed = False
        self.confirmed = False
        self.dispatches: list[dict] = []
        self.transcript_link = None
        self.transcript_html = ""
        self.found: list[str] = []
        self.lookups: set[str] = set()            # account hints already checked
        self.conflicts: set[str] = set()          # inconsistencies already recorded
        self.response_active = False
        self.user_speaking = False
        self.language = None  # pinned once the caller's language is known
        self.reply_style = None
        self.audio_item_id = None  # assistant item currently being spoken
        self.seen_calls: set[str] = set()
        self.pending_notes: list[str] = []
        self.background: set[asyncio.Task] = set()

    # ---- lifecycle -------------------------------------------------------

    async def run(self):
        case = await insforge.insert("cases", {"status": "open"})
        self.case_id = case["id"]
        await self.ui({"type": "case", "case_id": self.case_id})
        headers = {"Authorization": f"Bearer {os.environ['BOSON_API_KEY']}"}
        async with websockets.connect(BOSON_URL, additional_headers=headers, max_size=None) as boson:
            self.boson = boson
            # Higgs sends nothing until the first session.update.
            await self.send(patrick.session_update(self.tools))
            try:
                await asyncio.gather(self.from_browser(), self.from_boson())
            except WebSocketDisconnect as e:
                log.info("call %s: browser closed the socket (code %s)", self.case_id, e.code)
            except websockets.ConnectionClosed as e:
                # 1013 = Boson concurrency limit, 4429 = out of credit, 3000 = bad key.
                log.warning("call %s: Higgs Realtime closed the socket: %s", self.case_id, e)
                try:
                    await self.ui({"type": "ended", "reason": f"The voice service closed the call ({e})"})
                except Exception:
                    pass
            finally:
                for task in self.background:
                    task.cancel()
                if self.case_id:
                    await insforge.update("cases", {"id": self.case_id, "status": "open"}, {"status": "ended"})

    async def send(self, event: dict):
        await self.boson.send(json.dumps(event))

    async def ui(self, event: dict):
        await self.browser.send_text(json.dumps(event))

    # ---- browser -> Boson ------------------------------------------------

    async def from_browser(self):
        while True:
            msg = await self.browser.receive()
            if msg["type"] == "websocket.disconnect":
                raise WebSocketDisconnect()
            if msg.get("bytes"):
                audio = base64.b64encode(msg["bytes"]).decode()
                await self.send({"type": "input_audio_buffer.append", "audio": audio})
            elif msg.get("text"):
                await self.on_browser_event(json.loads(msg["text"]))

    async def on_browser_event(self, ev: dict):
        # The browser answers our "flush" with how much of Patrick's reply was
        # actually heard. Only the browser knows this, and Higgs needs it so
        # its memory of the conversation matches what the caller heard.
        if ev["type"] == "flushed" and ev.get("dropped") and ev.get("item_id"):
            await self.send({
                "type": "conversation.item.truncate",
                "item_id": ev["item_id"],
                "content_index": 0,
                "audio_end_ms": int(ev["played_ms"]),
            })

    # ---- Boson -> browser ------------------------------------------------

    async def from_boson(self):
        async for raw in self.boson:
            ev = json.loads(raw)
            t = ev["type"]

            if t == "response.output_audio.delta":
                if ev["item_id"] != self.audio_item_id:
                    self.audio_item_id = ev["item_id"]
                    await self.ui({"type": "audio_start", "item_id": ev["item_id"]})
                await self.browser.send_bytes(base64.b64decode(ev["delta"]))

            elif t == "input_audio_buffer.speech_started":
                # Barge-in. Higgs cancels its own response; we stop playback.
                self.user_speaking = True
                await self.ui({"type": "flush"})

            elif t == "input_audio_buffer.speech_stopped":
                self.user_speaking = False

            elif t == "response.created":
                self.response_active = True

            elif t == "response.output_audio_transcript.delta":
                await self.ui({"type": "transcript", "speaker": "patrick", "item_id": ev["item_id"],
                               "text": ev["delta"], "final": False})

            elif t == "response.output_audio_transcript.done":
                text = redact(ev["transcript"])
                await self.ui({"type": "transcript", "speaker": "patrick", "item_id": ev["item_id"],
                               "text": text, "final": True})
                self.on_turn("patrick", ev["item_id"], text)

            elif t == "conversation.item.input_audio_transcription.completed":
                text = redact(ev["transcript"])
                if any(ch.isalnum() for ch in text):
                    await self.ui({"type": "transcript", "speaker": "caller", "item_id": ev["item_id"],
                                   "text": text, "final": True})
                self.on_turn("caller", ev["item_id"], text)

            elif t == "response.done":
                self.response_active = False
                await self.on_response_done(ev["response"])

            elif t == "session.created":
                await self.ui({"type": "ready"})
                # Patrick speaks first: greeting and consent.
                await self.send({"type": "response.create", "response": {"instructions": patrick.GREETING}})

            elif t == "error":
                log.warning("boson error: %s", ev.get("error"))
                await self.ui({"type": "error", "error": ev.get("error")})

            elif t in ("session.idle_timeout", "session.max_duration_reached"):
                await self.ui({"type": "ended", "reason": t})

    def on_turn(self, speaker: str, item_id: str, text: str):
        """Store a finished transcript turn. Caller transcripts repeat with the
        same item_id as they grow, so only the newest scribe pass survives."""
        # The recognizer sometimes returns only "..." or noise. There is nothing to
        # store, translate or extract, and a text model must never be asked to guess.
        if not any(ch.isalnum() for ch in text):
            return
        if speaker == "caller":
            self.last_caller_text_at = time.monotonic()
        self.turns.setdefault(item_id, {"speaker": speaker})["text"] = text
        if old := self.scribes.get(item_id):
            old.cancel()
        self.scribes[item_id] = task = asyncio.create_task(self.scribe(speaker, item_id, text))
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def scribe(self, speaker: str, item_id: str, text: str):
        """Model Gateway pass over one turn, off the voice path: English
        translation, language tag, and (caller turns) the facts stated."""
        from tools.case_file import GLOSSARY
        ask = ("You prepare call transcripts. STRICT: work only from the words in the text. Never add, guess or "
               "complete anything the text does not literally say; if it is empty, unclear or a fragment, return "
               "it as it is with no facts. Translate the text to plain English and name its language "
               "(for mixed speech name both, e.g. 'Hindi and English'). Also give reply_style: how a voice agent "
               "should answer this speaker, naming the BASE language, e.g. 'Hinglish: Hindi as the base with English "
               "words mixed in', 'Spanglish: Spanish as the base with English words', or just 'English'. ")
        if speaker == "caller":
            ask += (f"Also extract facts the caller stated, using only these keys ({GLOSSARY}). Short English values. "
                    f"Known so far: {self.fields}. Put a key in facts only if this turn states it for the first time. "
                    "Put a key in corrections only if the caller explicitly takes back a known value "
                    "('sorry, actually it was...'). If instead this turn simply contradicts something known or said "
                    "earlier without acknowledging it (for example 'afternoon' earlier and '7 AM' now, or two "
                    "different amounts), do not treat it as a correction: set conflict to one English sentence "
                    "naming both values. Otherwise conflict is null. "
                    "Think like an investigator reading the whole call so far: if this turn leaves a gap, is vague "
                    "where a detail matters, or sounds implausible, set cross_question to the one short question "
                    "worth asking next (English); otherwise null. "
                    f"Call so far: {self.english_transcript()[-1500:]} "
                    "Set caller_done true only if the caller clearly signals they have nothing more to add "
                    "(for example 'okay, that is all, thank you', in any language). "
                    'Answer as JSON: {"english": "...", "language": "...", "reply_style": "...", "facts": {}, '
                    '"corrections": {}, "conflict": null, "cross_question": null, "caller_done": false}')
        else:
            ask += 'Answer as JSON: {"english": "...", "language": "..."}'
        try:
            out = await insforge.llm_json(ask, text)
        except Exception:
            log.exception("scribe failed")
            out = {}
        english, language = out.get("english") or text, out.get("language")
        if len(english) > 3 * len(text) + 40:  # a "translation" far longer than the speech was invented
            log.warning("scribe output rejected as ungrounded for turn %s", item_id)
            english, out = text, {}
        self.turns[item_id]["english"] = english
        await insforge.upsert("transcript_turns", {
            "case_id": self.case_id, "item_id": item_id, "speaker": speaker,
            "original_text": text, "english_text": english, "language": language}, on_conflict="case_id,item_id")
        if speaker == "caller":
            if language:
                await self.set_language(language, out.get("reply_style") or language)
            await self.backup(out.get("facts") or {}, out.get("corrections") or {})
            if out.get("conflict"):
                await self.on_conflict(out["conflict"])
            elif out.get("cross_question") and out["cross_question"] not in self.conflicts:
                # Live analysis: shown on the board and handed to Patrick quietly,
                # so his next question can probe it without talking over anyone.
                self.conflicts.add(out["cross_question"])
                await insforge.insert("inconsistencies", {"case_id": self.case_id, "kind": "question",
                                                          "description": out["cross_question"]})
                await self.note(f"Analyst suggestion, use it if it fits: ask \"{out['cross_question']}\"", speak=False)
            if out.get("caller_done"):
                await self.on_caller_done()

    async def on_conflict(self, conflict: str):
        """The caller contradicted themselves. Put it on the board and have
        Patrick raise it, even if the voice model let it slide."""
        if conflict in self.conflicts:
            return
        await self.invoke("flag_inconsistency", {"description": conflict}, source="backup")
        # Patrick often catches it himself. Let his reply finish, and only prompt
        # him if he did not already ask, so he never asks the same thing twice.
        for _ in range(20):
            if not self.response_active:
                break
            await asyncio.sleep(0.5)
        await asyncio.sleep(1.5)  # his transcript lands just after the audio
        last = [t for t in self.turns.values() if t["speaker"] == "patrick"][-1:]
        said = last[0]["text"] if last else ""
        asked = await insforge.llm_json(
            'Did the agent\'s last reply already ask the caller about this conflict? Answer as JSON: {"asked": true|false}',
            f"Conflict: {conflict}\nAgent's last reply: {said}")
        if not asked.get("asked"):
            await self.note(f"The caller's statements conflict: {conflict} You have not settled this yet. "
                            "Raise it kindly now and ask which one is right.")

    async def on_caller_done(self):
        """End detection. If Patrick did not propose on its own, do it for it and
        hand it the summary to read back."""
        await asyncio.sleep(3)
        if self.proposed_at_turn is None and not self.emergency:
            result = await self.invoke("propose_filing", {}, source="backup")
            await self.note(f"The caller signalled they are done. Proposal: {json.dumps(result)}")

    async def backup(self, facts: dict, corrections: dict):
        """Higgs does not call tools on every turn. After giving Patrick a head
        start, the gateway fills in whatever it missed, through the same tools."""
        await asyncio.sleep(4)
        for field, value in facts.items():
            if value and field not in self.fields:
                await self.invoke("update_case_file", {"field": field, "value": str(value)}, source="backup")
        for field, value in corrections.items():
            if value and self.fields.get(field) != str(value):
                await self.invoke("update_case_file", {"field": field, "value": str(value)}, source="backup")
                # A corrected fact settles the open conflict about it.
                await insforge.update("inconsistencies", {"case_id": self.case_id, "status": "open"},
                                      {"status": "resolved"})
        if not self.case_type and "what_happened" in self.fields:
            await self.invoke("classify_case", {}, source="backup")
        last4 = self.fields.get("account_last4")
        if self.case_type == "scam_fraud" and last4 and last4 not in self.lookups:
            result = await self.invoke("lookup_transactions", {"account_hint": last4}, source="backup")
            await self.note(f"Bank records for the account ending {last4}: {json.dumps(result)}")

    def english_transcript(self) -> str:
        return "\n".join(f"{t['speaker']}: {t.get('english') or t['text']}" for t in self.turns.values())

    async def maybe_find_authorities(self):
        """Start a background search for every destination that is ready. Called
        whenever a fact or the case type changes, so the bank search can start
        later than the police search if the bank's name arrives later."""
        from tools import authorities
        for dest in authorities.ready_destinations(self):
            self.searched_roles.add(dest["role"])
            self.spawn(self.search_and_report(dest))

    async def search_and_report(self, dest: dict):
        from tools import authorities
        self.searching += 1
        row = await authorities.search_destination(self, dest)
        self.searching -= 1
        if row:
            self.found.append(row["name"])
            from tools import forms
            self.spawn(forms.prepare_form(self, row))
        if self.searching == 0 and self.found:
            names, self.found = ", ".join(self.found), []
            await self.note(f"The background search found these offices: {names}. Mention in one short sentence "
                            "that you have found the right offices and will tell the caller before anything is sent, "
                            "then continue your questions.")

    async def set_language(self, language: str, reply_style: str):
        if language != self.language:
            self.language, self.reply_style = language, reply_style
            await insforge.update("cases", {"id": self.case_id}, {"language": language})
            await self.send({"type": "session.update", "session": {"instructions": patrick.instructions(reply_style)}})

    # ---- tools -----------------------------------------------------------

    async def on_response_done(self, response: dict):
        calls = [i for i in response.get("output", [])
                 if i.get("type") == "function_call" and i["call_id"] not in self.seen_calls]
        for call in calls:
            self.seen_calls.add(call["call_id"])
            output = await self.run_tool(call["name"], call.get("arguments") or "{}")
            await self.send({"type": "conversation.item.create",
                             "item": {"type": "function_call_output", "call_id": call["call_id"],
                                      "output": output}})
        if calls:
            # Mandatory: without this Higgs stays silent after a tool call.
            await self.send({"type": "response.create"})
        else:
            await self.flush_notes()

    async def run_tool(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments)
        except json.JSONDecodeError:
            args = {}
        result = await self.invoke(name, args, source="patrick")
        if isinstance(result, dict):
            # Tool results are English, which pulls Higgs back to English. Remind it every time.
            result = {**result, "speak_in": self.reply_style or "the caller's language"}
        return result if isinstance(result, str) else json.dumps(result)

    async def invoke(self, name: str, args: dict, source: str):
        """The one path every tool runs through, whether the voice model called
        it (source 'patrick') or the gateway's backup did (source 'backup')."""
        status = "done"
        try:
            result = await self.handlers[name](self, **args)
        except Exception as e:  # a broken tool must never kill the call
            log.exception("tool %s failed", name)
            status, result = "error", {"error": str(e)}
        # The tool log reaches the board through InsForge Realtime; do not wait for the write.
        self.spawn(insforge.insert("tool_events", {"case_id": self.case_id, "name": name, "args": args,
                                                   "result": result, "status": status, "source": source}))
        return result

    def spawn(self, coro):
        """Run a slow tool in the background so Patrick keeps talking."""
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def note(self, text: str, speak: bool = True):
        """Tell Patrick something a background task found, without cutting anyone off.
        speak=False only adds it to his context; he uses it on his next turn."""
        if not speak:
            await self.send({"type": "conversation.item.create",
                             "item": {"type": "message", "role": "user",
                                      "content": [{"type": "input_text",
                                                   "text": f"[Case board update, not spoken by the caller] {text}"}]}})
            return
        self.pending_notes.append(text)
        await self.flush_notes()

    async def flush_notes(self):
        if not self.pending_notes or self.response_active or self.user_speaking:
            return
        text = " ".join(self.pending_notes)
        self.pending_notes.clear()
        # Higgs rejects the system role, so notes arrive as bracketed user text.
        await self.send({"type": "conversation.item.create",
                         "item": {"type": "message", "role": "user",
                                  "content": [{"type": "input_text",
                                               "text": f"[Case board update, not spoken by the caller] {text}"}]}})
        await self.send({"type": "response.create"})
