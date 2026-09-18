"""Case Closed voice gateway. Run locally: uvicorn main:app --reload --port 8000"""
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

app = FastAPI(title="Case Closed gateway")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.websocket("/ws/call")
async def call(ws: WebSocket):
    # CORS middleware does not cover WebSockets, so check the origin by hand.
    if ws.headers.get("origin") not in ALLOWED_ORIGINS:
        await ws.close(code=4403)
        return
    await ws.accept()
    await CallSession(ws, TOOLS, HANDLERS).run()
