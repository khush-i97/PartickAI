"""Relay between one browser call and one Higgs Realtime session.

Browser -> gateway: binary frames are PCM16 24 kHz mic audio; text frames are
JSON control messages ({"type": "flushed", ...}).
Gateway -> browser: binary frames are Rook's PCM16 24 kHz audio; text frames
are JSON events for the UI (transcripts, tool calls, flush requests).

The Boson key stays here. Tool calls are executed here, never in the browser.
"""
import asyncio
import base64
import json
import logging
import os

import websockets
from fastapi import WebSocket, WebSocketDisconnect

import insforge
import rook
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
            await self.send(rook.session_update(self.tools))
            try:
                await asyncio.gather(self.from_browser(), self.from_boson())
            except (WebSocketDisconnect, websockets.ConnectionClosed):
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
        # The browser answers our "flush" with how much of Rook's reply was
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
                await self.ui({"type": "transcript", "speaker": "rook", "item_id": ev["item_id"],
                               "text": ev["delta"], "final": False})

            elif t == "response.output_audio_transcript.done":
                text = redact(ev["transcript"])
                await self.ui({"type": "transcript", "speaker": "rook", "item_id": ev["item_id"],
                               "text": text, "final": True})
                self.on_turn("rook", ev["item_id"], text)

            elif t == "conversation.item.input_audio_transcription.completed":
                text = redact(ev["transcript"])
                await self.ui({"type": "transcript", "speaker": "caller", "item_id": ev["item_id"],
                               "text": text, "final": True})
                self.on_turn("caller", ev["item_id"], text)

            elif t == "response.done":
                self.response_active = False
                await self.on_response_done(ev["response"])

            elif t == "session.created":
                await self.ui({"type": "ready"})
                # Rook speaks first: greeting and consent.
                await self.send({"type": "response.create", "response": {"instructions": rook.GREETING}})

            elif t == "error":
                log.warning("boson error: %s", ev.get("error"))
                await self.ui({"type": "error", "error": ev.get("error")})

            elif t in ("session.idle_timeout", "session.max_duration_reached"):
                await self.ui({"type": "ended", "reason": t})

    def on_turn(self, speaker: str, item_id: str, text: str):
        """Store a finished transcript turn. Caller transcripts repeat with the
        same item_id as they grow, so only the newest scribe pass survives."""
        if not text.strip():
            return
        self.turns.setdefault(item_id, {"speaker": speaker})["text"] = text
        if old := self.scribes.get(item_id):
            old.cancel()
        self.scribes[item_id] = task = asyncio.create_task(self.scribe(speaker, item_id, text))
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def scribe(self, speaker: str, item_id: str, text: str):
        """Model Gateway pass over one turn, off the voice path: English
        translation, language tag, and (caller turns) the facts stated."""
        from tools.case_file import FIELDS
        ask = ("You prepare call transcripts. Translate the text to plain English and name its language "
               "(for mixed speech name both, e.g. 'Hindi and English'). Also give reply_style: how a voice agent "
               "should answer this speaker, naming the BASE language, e.g. 'Hinglish: Hindi as the base with English "
               "words mixed in', 'Spanglish: Spanish as the base with English words', or just 'English'. ")
        if speaker == "caller":
            ask += (f"Also extract facts the caller stated, using only these keys: {FIELDS}. Short English values. "
                    f"Known so far: {self.fields}. Include a key only if this turn states or corrects it. "
                    'Answer as JSON: {"english": "...", "language": "...", "reply_style": "...", "facts": {}}')
        else:
            ask += 'Answer as JSON: {"english": "...", "language": "..."}'
        try:
            out = await insforge.llm_json(ask, text)
        except Exception:
            log.exception("scribe failed")
            out = {}
        english, language = out.get("english") or text, out.get("language")
        self.turns[item_id]["english"] = english
        await insforge.upsert("transcript_turns", {
            "case_id": self.case_id, "item_id": item_id, "speaker": speaker,
            "original_text": text, "english_text": english, "language": language}, on_conflict="case_id,item_id")
        if speaker == "caller":
            if language:
                await self.set_language(language, out.get("reply_style") or language)
            await self.backup(out.get("facts") or {})

    async def backup(self, facts: dict):
        """Higgs does not call tools on every turn. After giving Rook a head
        start, the gateway fills in whatever it missed, through the same tools."""
        await asyncio.sleep(4)
        for field, value in facts.items():
            if value and field not in self.fields:
                await self.invoke("update_case_file", {"field": field, "value": str(value)}, source="backup")
        if not self.case_type and "what_happened" in self.fields:
            await self.invoke("classify_case", {}, source="backup")
        last4 = self.fields.get("account_last4")
        if self.case_type == "scam_fraud" and last4 and last4 not in self.lookups:
            result = await self.invoke("lookup_transactions", {"account_hint": last4}, source="backup")
            await self.note(f"Bank records for the account ending {last4}: {json.dumps(result)}")

    def english_transcript(self) -> str:
        return "\n".join(f"{t['speaker']}: {t.get('english') or t['text']}" for t in self.turns.values())

    async def maybe_find_authorities(self):
        """Starts the background authority search once case type and location are known (milestone 3)."""

    async def set_language(self, language: str, reply_style: str):
        if language != self.language:
            self.language, self.reply_style = language, reply_style
            await insforge.update("cases", {"id": self.case_id}, {"language": language})
            await self.send({"type": "session.update", "session": {"instructions": rook.instructions(reply_style)}})

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
        result = await self.invoke(name, args, source="rook")
        if isinstance(result, dict):
            # Tool results are English, which pulls Higgs back to English. Remind it every time.
            result = {**result, "speak_in": self.reply_style or "the caller's language"}
        return result if isinstance(result, str) else json.dumps(result)

    async def invoke(self, name: str, args: dict, source: str):
        """The one path every tool runs through, whether the voice model called
        it (source 'rook') or the gateway's backup did (source 'backup')."""
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
        """Run a slow tool in the background so Rook keeps talking."""
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)

    async def note(self, text: str):
        """Tell Rook something a background task found, without cutting anyone off."""
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
