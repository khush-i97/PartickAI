"""Render Patrick's avatar clips with Higgs Avatar, from one portrait image.

    cd gateway && .venv/bin/python avatar/render.py path/to/patrick.jpg

Higgs Avatar is not a live conversation model (about five seconds to the first
frame), so the board plays short pre-rendered loops instead: one while Patrick
listens and two while he speaks. His voice always comes live from Higgs
Realtime; these clips are played muted. Output: frontend/public/avatar/.
"""
import base64
import io
import os
import sys
import time
import wave
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
OUT = ROOT / "frontend" / "public" / "avatar"
API = "https://api.boson.ai/v1/videos"
HEADERS = {"Authorization": f"Bearer {os.environ['BOSON_API_KEY']}"}
VOICE = os.getenv("PATRICK_VOICE", "marcus")

TALK = {
    "talk1": "I see. Walk me through it slowly, from the first moment something felt wrong. Every detail helps, "
             "even the small ones. Who contacted you, what did they say, and what did you do next?",
    "talk2": "Thank you, that is useful. Let me check one thing against the record before we go on. "
             "Dates and amounts matter here, so I want to be sure we have them exactly right.",
}


def silence(seconds: int) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000)
        w.writeframes(b"\0\0" * 24000 * seconds)
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode()


def render(name: str, image: str, **driver):
    r = httpx.post(API, headers=HEADERS, timeout=120,
                   json={"model": "higgs-avatar", "ref_image": image, "size": "640x640", **driver})
    r.raise_for_status()
    video_id = r.json()["id"]
    while True:
        video = httpx.get(f"{API}/{video_id}", headers=HEADERS, timeout=60).json()
        if video["status"] == "completed":
            break
        if video["status"] == "failed":
            sys.exit(f"{name} failed: {video.get('error')}")
        time.sleep(2)
    content = httpx.get(f"{API}/{video_id}/content", headers=HEADERS, timeout=300)
    content.raise_for_status()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.mp4").write_bytes(content.content)
    print(f"{name}.mp4  {len(content.content) // 1024} KB")


if __name__ == "__main__":
    path = Path(sys.argv[1])
    mime = {"png": "image/png", "webp": "image/webp"}.get(path.suffix.lower().lstrip("."), "image/jpeg")
    image = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    render("idle", image, input=silence(8))
    for name, line in TALK.items():
        render(name, image, input_tts={"model": "higgs-tts-3", "input": line, "voice": VOICE})
    (OUT / "poster.jpg").write_bytes(path.read_bytes()) if mime == "image/jpeg" else None
