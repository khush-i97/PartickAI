"""Thin client for InsForge. There is no Python SDK, so this uses the REST API
(PostgREST style records, storage) and the Model Gateway's OpenRouter key."""
import json
import os

import httpx

_http = httpx.AsyncClient(timeout=60)
LLM_MODEL = os.getenv("LLM_MODEL", "google/gemini-2.5-flash")


def _url(path: str) -> str:
    return os.environ["INSFORGE_URL"].rstrip("/") + path


def _headers(extra: dict | None = None) -> dict:
    return {"Authorization": f"Bearer {os.environ['INSFORGE_API_KEY']}", **(extra or {})}


# ---- database ---------------------------------------------------------------

async def insert(table: str, row: dict) -> dict:
    r = await _http.post(_url(f"/api/database/records/{table}"), json=[row],
                         headers=_headers({"Prefer": "return=representation"}))
    r.raise_for_status()
    return r.json()[0]


async def upsert(table: str, row: dict, on_conflict: str) -> dict:
    r = await _http.post(_url(f"/api/database/records/{table}"), json=[row],
                         params={"on_conflict": on_conflict},
                         headers=_headers({"Prefer": "return=representation,resolution=merge-duplicates"}))
    r.raise_for_status()
    return r.json()[0]


async def update(table: str, match: dict, patch: dict) -> list[dict]:
    r = await _http.patch(_url(f"/api/database/records/{table}"), json=patch,
                          params={k: f"eq.{v}" for k, v in match.items()},
                          headers=_headers({"Prefer": "return=representation"}))
    r.raise_for_status()
    return r.json()


async def select(table: str, **params) -> list[dict]:
    r = await _http.get(_url(f"/api/database/records/{table}"), params=params, headers=_headers())
    r.raise_for_status()
    return r.json()


# ---- model gateway ----------------------------------------------------------

async def llm_json(system: str, user: str, model: str | None = None) -> dict:
    """One JSON answer from the Model Gateway. All text work goes through here
    so the voice model is never blocked by it."""
    r = await _http.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={"model": model or LLM_MODEL, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])
