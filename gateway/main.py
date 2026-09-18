"""Patrick voice gateway. Run locally: uvicorn main:app --reload --port 8000"""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from relay import CallSession  # noqa: E402
from tools import HANDLERS, TOOLS  # noqa: E402

logging.basicConfig(level=logging.INFO)

# Only the Sites domain and localhost may talk to the gateway.
ALLOWED_ORIGINS = [o.strip() for o in os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]

app = FastAPI(title="Patrick gateway")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/cases/{case_id}/packet")
async def packet(case_id: str):
    """The drafted emails and their files, for the caller to review.

    Read-only: it builds the documents and hands them back. There is no send
    endpoint on purpose — sending a report to a real police force is a decision
    someone makes deliberately, not something this route can be talked into."""
    import outbox  # noqa: PLC0415 — keeps the websocket path's import cost unchanged
    packet = await outbox.build_packet(case_id)
    return {k: v for k, v in packet.items() if k != "documents"}  # bytes are not JSON


@app.post("/api/demo")
async def demo_case():
    """Fill a case without a microphone, for showing the thing to people.

    The conversation is canned; the offices, their forms and the packet are
    found live, so the demo exercises the parts that can actually break."""
    import demo  # noqa: PLC0415
    return await demo.seed()


@app.post("/api/cases/{case_id}/send/{authority_id}")
async def send(case_id: str, authority_id: str):
    """Send one drafted email with its files attached.

    Where it lands is mailer.py's decision, not this route's: with SAFE_MODE on
    it goes to the demo inbox with the real office named in the subject, and
    mailer refuses outright if that inbox is not configured."""
    import outbox  # noqa: PLC0415
    return await outbox.send_draft(case_id, authority_id)


@app.websocket("/ws/call")
async def call(ws: WebSocket):
    # CORS middleware does not cover WebSockets, so check the origin by hand.
    if ws.headers.get("origin") not in ALLOWED_ORIGINS:
        await ws.close(code=4403)
        return
    await ws.accept()
    await CallSession(ws, TOOLS, HANDLERS).run()
