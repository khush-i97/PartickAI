"""find_authorities: background task. Live web search (Parallel, or Tavily as the
fallback), then the Model
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


# Places a caller names when asked where something happened, which are not the
# city that decides which office handles it. "ASU" became "A C University",
# which searched as a city and filed a Phoenix wallet with police in Leesburg,
# Virginia. These belong in place_lost.
VENUE_WORDS = ("university", "college", "campus", "school", "airport", "station", "terminal",
               "mall", "stadium", "hospital", "library", "hotel", "street", "avenue", "road")


def usable_city(location: str | None) -> str | None:
    """The city a search can trust, or None when the caller has not really given
    one yet. A search run on a bad city does not fail — it confidently returns
    the wrong town's police force, which is worse than waiting."""
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    if len(parts) < 2:          # "Phoenix" alone cannot pick between the Phoenixes
        return None
    city = parts[0]
    if len(city) < 3 or any(w in city.lower() for w in VENUE_WORDS):
        return None
    return city


def ready_destinations(session) -> list[dict]:
    """Destinations whose search can start: every {placeholder} in the query is known."""
    city = usable_city(session.fields.get("location"))
    if not session.case_type or not city:
        return []
    parts = [p.strip() for p in session.fields["location"].split(",")]
    known = {**session.fields, "city": city, "country": parts[-1], "state_or_country": parts[-1],
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
    # Search excerpts rarely carry an inbox even when the office publishes one:
    # Leesburg's police email sits far down their contact page. Worth one read.
    if not contact.get("email") and contact.get("source_url"):
        contact["email"] = await published_email(contact["source_url"])

    order = [d["role"] for d in ROUTING["case_types"][session.case_type]["destinations"]]
    row = await insforge.insert("authorities", {
        "case_id": session.case_id, "role": dest["role"], "rank": order.index(dest["role"]) + 1,
        "is_cached": cached, **{k: contact.get(k) for k in
                                ("name", "handles", "reason", "email", "form_url", "phone", "address", "source_url")}})
    session.authorities[dest["role"]] = row
    return row


async def resolve_city(*clues: str | None) -> str | None:
    """Work out the city from what the caller already said.

    "ASU", "Arizona State University", "Sky Harbor" — a person hearing these
    knows the city, and asking anyway is the single most irritating thing this
    agent does. Only a well known place is accepted: the model is told to answer
    null rather than guess, because a guessed city routes the report to the
    wrong force, and the caller is asked as a last resort."""
    text = " · ".join(c for c in clues if c and c.strip())
    if not text.strip():
        return None
    try:
        out = await insforge.llm_json(
            "Which city is this place in? The text names a place from a phone call: a university, campus, airport, "
            "station, landmark or neighbourhood, possibly misheard or abbreviated (ASU, A C University and Arizona "
            "State University are the same place). Answer with the city and its state or country, like "
            '"Tempe, Arizona" or "Mumbai, India". If the place is ambiguous, unknown to you, or could be in several '
            "countries, answer null — a wrong city sends a police report to the wrong force. "
            'Answer as JSON: {"location": "City, State" or null}',
            text)
        return usable_city(out.get("location")) and out["location"].strip()
    except Exception:
        log.exception("could not resolve a city from %r", text)
        return None


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# An inbox someone reads, rather than a newsletter or a webmaster alias.
PREFERRED = ("police", "report", "complaint", "fraud", "record", "info", "contact", "help", "service", "support")
JUNK = ("example.", "sentry.", "wixpress.", "@2x.", ".png", ".jpg", ".gif", "no-reply", "noreply", "donotreply")


async def published_email(source_url: str) -> str | None:
    """The office's own published address, read off its own page.

    Only ever copied, never constructed, and only accepted on the same domain as
    the page it came from — an address invented for a police force would send a
    report into nowhere and the caller would never know."""
    from . import forms  # circular at module level: forms imports nothing from here
    try:
        page = await asyncio.wait_for(forms.read_page(source_url), 20)
    except Exception as e:
        log.warning("could not read %s for an email: %s", source_url, e)
        return None
    if not page:
        return None

    domain = re.sub(r"^www\.", "", (re.search(r"https?://([^/]+)", source_url) or [None, ""])[1]).lower()
    root = ".".join(domain.split(".")[-2:]) if domain else ""
    found = []
    for raw in EMAIL_RE.findall(page):
        address = raw.strip(".,;:)").lower()
        if any(j in address for j in JUNK) or (root and not address.endswith(root)):
            continue
        if address not in found:
            found.append(address)
    if not found:
        return None
    return next((a for a in found if any(p in a.split("@")[0] for p in PREFERRED)), found[0])


async def live_lookup(dest: dict) -> dict | None:
    """Both phrasings go out together. Parallel takes a list of queries in one
    request, so asking twice costs one round trip instead of two, and the model
    picks from the pooled results rather than settling for whatever the first
    phrasing happened to return."""
    queries = [dest["query"], f"{dest['label']} official website contact {dest['query'].split()[0]}"]
    return await search_once(dest, queries)


async def search_once(dest: dict, queries: list[str]) -> dict | None:
    results = await web_search(queries, f"Find the official page of: {dest['label']}. I need the organization's own "
                                        "website or a government site, with its phone, email, postal address and any "
                                        "online report form.")
    if not results:
        return None
    out = await insforge.llm_json(
        "You pick the one official organization that accepts this kind of report, from web search results. "
        "STRICT SOURCE RULE: source_url must be on the organization's own website (for a company or bank, its own "
        "domain, e.g. chase.com for Chase) or, for a public agency, that agency's government domain. Pages about "
        "the organization on any other site, including other government sites, nonprofits, blogs, news, directories "
        "and law firms, do not count. If no result passes, answer found false. "
        "Name the specific office or service (e.g. 'SF 311', not the website name). "
        "SERVES THE RIGHT PLACE: when the query names a city, state or country, the organization must actually "
        "serve it. A police force or city office for a different town is wrong even when the page looks official, "
        "and a report filed there goes nowhere; answer found false rather than offering it. National agencies are "
        "fine for a national query. "
        "Copy contact details only if they appear in the results; never invent them. "
        "address is the office's postal or walk-in address, copied exactly as the results write it, or null. "
        "Many agencies publish only a phone and an online form: null is the right answer then. Never assemble an "
        "address from a city name, and never guess a street or postcode — a wrong address on a filed report is "
        "worse than none. "
        'Answer as JSON: {"found": true|false, "name": "...", "handles": "what they handle, short", '
        '"reason": "one sentence on why this is the right office", "email": "... or null", '
        '"form_url": "online report form URL or null", "phone": "... or null", '
        '"address": "... or null", "source_url": "the result URL used"}',
        f"Needed: {dest['label']}\nSearch queries: {'; '.join(queries)}\nResults: {json.dumps(results)}")
    return out if out.get("found") and out.get("name") and out.get("source_url") else None


async def web_search(queries: list[str], objective: str) -> list[dict]:
    """Every phrasing of the question, searched at once. Parallel takes the whole
    list in one objective-driven request; Tavily takes one query per request, so
    those go out concurrently instead of one after another. Either way the
    results come back pooled and deduplicated by URL."""
    async with httpx.AsyncClient(timeout=25) as http:
        if os.getenv("PARALLEL_API_KEY", "").strip():
            try:
                r = await http.post("https://api.parallel.ai/v1/search",
                                    headers={"x-api-key": os.environ["PARALLEL_API_KEY"]},
                                    json={"objective": objective, "search_queries": queries})
                r.raise_for_status()
                return _dedupe({"title": x.get("title") or "", "url": x["url"],
                                "content": " ".join(x.get("excerpts") or [])[:1500]} for x in r.json()["results"])
            except Exception as e:
                log.warning("Parallel search failed, falling back to Tavily: %s", e)

        async def tavily(query: str) -> list[dict]:
            r = await http.post("https://api.tavily.com/search",
                                headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
                                json={"query": query, "search_depth": "advanced", "max_results": 8})
            r.raise_for_status()
            return [{"title": x["title"], "url": x["url"], "content": x["content"][:1200]} for x in r.json()["results"]]

        # One bad phrasing should not lose the results the other one found.
        batches = await asyncio.gather(*(tavily(q) for q in queries), return_exceptions=True)
        for b in batches:
            if isinstance(b, Exception):
                log.warning("Tavily search failed for one query: %s", b)
        return _dedupe(r for b in batches if not isinstance(b, Exception) for r in b)


def _dedupe(results) -> list[dict]:
    """Same page found by two phrasings is one result, keeping the longer excerpt."""
    best: dict[str, dict] = {}
    for r in results:
        seen = best.get(r["url"])
        if not seen or len(r["content"]) > len(seen["content"]):
            best[r["url"]] = r
    return list(best.values())[:10]


def cached_lookup(case_type: str, role: str) -> dict | None:
    """Fallback for the demo scenario only, shown on screen as a cached result."""
    try:
        return json.loads(CACHE_FILE.read_text()).get(case_type, {}).get(role)
    except FileNotFoundError:
        return None
