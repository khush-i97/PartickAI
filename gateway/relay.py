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

import rook

log = logging.getLogger("relay")
BOSON_URL = "wss://api.boson.ai/v1/realtime?model=higgs-realtime"


class CallSession:
    def __init__(self, browser: WebSocket, tools: list[dict], handlers: dict):
        self.browser = browser
        self.tools = tools
        self.handlers = handlers  # tool name -> async fn(session, **args) -> str|dict
        self.boson = None
        self.response_active = False
        self.user_speaking = False
        self.language = None  # pinned once the caller's language is known
        self.audio_item_id = None  # assistant item currently being spoken
        self.seen_calls: set[str] = set()
        self.pending_notes: list[str] = []
        self.background: set[asyncio.Task] = set()

    # ---- lifecycle -------------------------------------------------------

    async def run(self):
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
                await self.ui({"type": "transcript", "speaker": "rook", "item_id": ev["item_id"],
                               "text": ev["transcript"], "final": True})
                await self.on_turn("rook", ev["item_id"], ev["transcript"])

            elif t == "conversation.item.input_audio_transcription.completed":
                await self.ui({"type": "transcript", "speaker": "caller", "item_id": ev["item_id"],
                               "text": ev["transcript"], "final": True})
                await self.on_turn("caller", ev["item_id"], ev["transcript"])

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

    async def on_turn(self, speaker: str, item_id: str, text: str):
        """Called for every finished transcript (caller transcripts repeat with
        the same item_id as they grow, so anything stored must upsert)."""
        if speaker == "caller":
            # Milestone 1 heuristic; the Model Gateway language tag replaces it.
            devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
            await self.set_language("Hinglish (Hindi mixed with English, romanized)" if devanagari else None)

    async def set_language(self, language: str | None):
        if language and language != self.language:
            self.language = language
            await self.send({"type": "session.update", "session": {"instructions": rook.instructions(language)}})

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
            await self.ui({"type": "tool", "name": name, "args": args})
            result = await self.handlers[name](self, **args)
        except Exception as e:  # a broken tool must never kill the call
            log.exception("tool %s failed", name)
            result = {"error": str(e)}
        return result if isinstance(result, str) else json.dumps(result)

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
