"""Form ready: read the real complaint form, list the fields it asks for, and
map the case file onto them. Runs in the background after an office with a
web form is found. Nothing is opened in a browser and nothing is submitted:
pressing submit on a real agency's form is left to a person."""
import logging
import os

import httpx

import insforge
from .case_file import FIELDS, ROUTING

log = logging.getLogger("forms")


async def prepare_form(session, authority: dict):
    needs = next((d["needs"] for d in ROUTING["case_types"][session.case_type]["destinations"]
                  if d["role"] == authority["role"]), [])
    fields, source = [], "standard"
    if authority.get("form_url"):
        try:
            fields = await read_live_form(authority)
            source = "form"
        except Exception as e:
            log.warning("could not read %s: %s", authority["form_url"], e)
    if not fields:
        # The page showed no fields (many portals hide them behind a login or a
        # multi step app), so fall back to what routing.yaml says this office needs.
        fields = [{"label": k.replace("_", " ").capitalize(), "required": True, "maps_to": k} for k in needs]
        source = "standard"

    for n, f in enumerate(fields[:14]):
        maps_to = f.get("maps_to") if f.get("maps_to") in FIELDS else None
        await insforge.insert("form_fields", {
            "case_id": session.case_id, "authority_id": authority["id"], "position": n, "label": str(f["label"])[:120],
            "required": bool(f.get("required")), "maps_to": maps_to, "source": source})

    missing = [f["maps_to"] for f in fields if f.get("required") and f.get("maps_to") in FIELDS
               and f["maps_to"] not in session.fields and f["maps_to"] not in session.asked_for]
    if missing:
        session.asked_for.update(missing)
        await session.note(f"The {authority['name']} form also requires: {', '.join(missing[:3])}. The caller has NOT "
                           "given you these yet. Ask for them, one at a time, and save each answer with update_case_file.")


async def read_live_form(authority: dict) -> list[dict]:
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post("https://api.tavily.com/extract",
                            headers={"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"},
                            json={"urls": [authority["form_url"]], "extract_depth": "advanced"})
        r.raise_for_status()
    page = (r.json().get("results") or [{}])[0].get("raw_content", "")[:14000]
    if not page:
        return []
    out = await insforge.llm_json(
        "This is the text of an organization's online report or complaint form page. List the information the "
        "form asks the person to provide, in order, using the page's own wording for each label. Only list what "
        "the page really asks for or clearly says you will need; if it shows no fields or requirements, return an "
        f"empty list. For each, give maps_to: the one key from {FIELDS} that answers it, or null if none fits. "
        'Answer as JSON: {"fields": [{"label": "...", "required": true|false, "maps_to": "key or null"}]}',
        f"Organization: {authority['name']}\nURL: {authority['form_url']}\nPage text:\n{page}")
    return out.get("fields") or []
