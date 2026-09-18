"""find_authorities: background task. Live web search (Tavily), then the Model
Gateway extracts one official contact per destination. Patrick keeps talking while
it runs; results land on the board through InsForge Realtime."""
import asyncio
import json
import logging
import os
import re
from pathlib import Path

import httpx

import insforge
from .case_file import ROUTING

log = logging.getLogger("authorities")
CACHE_FILE = Path(__file__).resolve().parents[2] / "db" / "cached_authorities.json"
SEARCH_TIMEOUT = 25  # seconds per destination before the cached fallback is used

FIND_AUTHORITIES = {
    "type": "function",
    "name": "find_authorities",
    "description": ("Start the background search for the real organizations that handle this case. Call it as soon "
                    "as you know the case type and the caller's city and country. It returns at once; keep talking."),
    "parameters": {"type": "object", "required": ["case_type", "location"], "properties": {
        "case_type": {"type": "string", "enum": list(ROUTING["case_types"])},
        "location": {"type": "string", "description": "City and state or country, in English."}}},
}


async def find_authorities(session, case_type: str, location: str):
    if case_type in ROUTING["case_types"]:
        session.case_type = session.case_type or case_type
    session.fields.setdefault("location", location)
    await session.maybe_find_authorities()
    return {"started": True, "note": "Searching in the background. Results appear on the board. Keep the "
                                     "conversation going; you will be told when the offices are found."}


def ready_destinations(session) -> list[dict]:
    """Destinations whose search can start: every {placeholder} in the query is known."""
    if not session.case_type or not session.fields.get("location"):
        return []
    parts = [p.strip() for p in session.fields["location"].split(",")]
    known = {**session.fields, "city": parts[0], "country": parts[-1], "state_or_country": parts[-1],
             "issue": session.fields.get("what_happened", "")}
    ready = []
    for dest in ROUTING["case_types"][session.case_type]["destinations"]:
        needed = re.findall(r"{(\w+)}", dest["search"])
        if dest["role"] not in session.searched_roles and all(known.get(k) for k in needed):
            ready.append({**dest, "query": dest["search"].format(**known)})
    return ready


async def search_destination(session, dest: dict):
    search = await insforge.insert("authority_searches", {"case_id": session.case_id, "query": dest["query"]})
    cached = False
    try:
        contact = await asyncio.wait_for(live_lookup(dest), SEARCH_TIMEOUT)
    except Exception as e:
        log.warning("live search failed for %s: %s", dest["role"], e)
        contact = None
    if not contact:
        contact, cached = cached_lookup(session.case_type, dest["role"]), True
    await insforge.update("authority_searches", {"id": search["id"]},
                          {"status": "done" if contact and not cached else "failed", "result_count": 1 if contact else 0})
    if not contact:
        return None
    order = [d["role"] for d in ROUTING["case_types"][session.case_type]["destinations"]]
    row = await insforge.insert("authorities", {
        "case_id": session.case_id, "role": dest["role"], "rank": order.index(dest["role"]) + 1,
        "is_cached": cached, **{k: contact.get(k) for k in
                                ("name", "handles", "reason", "email", "form_url", "phone", "source_url")}})
    session.authorities[dest["role"]] = row
    return row


async def live_lookup(dest: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post("https://api.tavily.com/search",
                            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
                            json={"query": dest["query"], "search_depth": "advanced", "max_results": 6})
        r.raise_for_status()
    results = [{"title": x["title"], "url": x["url"], "content": x["content"][:1200]} for x in r.json()["results"]]
    out = await insforge.llm_json(
        "You pick the one official organization that accepts this kind of report, from web search results. "
        "Prefer the organization's own site or a government site. Discard blogs, news, directories, law firms "
        "and anything unofficial. Copy contact details only if they appear in the results; never invent them. "
        'Answer as JSON: {"found": true|false, "name": "...", "handles": "what they handle, short", '
        '"reason": "one sentence on why this is the right office", "email": "... or null", '
        '"form_url": "online report form URL or null", "phone": "... or null", "source_url": "the result URL used"}',
        f"Needed: {dest['label']}\nSearch query: {dest['query']}\nResults: {json.dumps(results)}")
    return out if out.get("found") and out.get("name") and out.get("source_url") else None


def cached_lookup(case_type: str, role: str) -> dict | None:
    """Fallback for the demo scenario only, shown on screen as a cached result."""
    try:
        return json.loads(CACHE_FILE.read_text()).get(case_type, {}).get(role)
    except FileNotFoundError:
        return None
