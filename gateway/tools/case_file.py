"""Fast tools: they write to the case board and return at once."""
from datetime import datetime, timezone
from pathlib import Path

import yaml

import insforge
from redact import redact

ROUTING = yaml.safe_load((Path(__file__).resolve().parents[2] / "routing.yaml").read_text())
FIELDS = ROUTING["fields"]

UPDATE_CASE_FILE = {
    "type": "function",
    "name": "update_case_file",
    "description": ("Write one fact to the case file the moment the caller states or corrects it. "
                    "Call it for every new fact. Write the value in English, short and factual. "
                    "If the caller corrects a fact, call it again with the same field."),
    "parameters": {"type": "object", "required": ["field", "value"], "properties": {
        "field": {"type": "string", "enum": FIELDS},
        "value": {"type": "string"}}},
}

FLAG_INCONSISTENCY = {
    "type": "function",
    "name": "flag_inconsistency",
    "description": ("Record a conflict between two details, for example the caller's date versus the bank record. "
                    "After calling it, raise the conflict kindly and ask which one is right."),
    "parameters": {"type": "object", "required": ["description"], "properties": {
        "description": {"type": "string", "description": "One English sentence naming both conflicting details."}}},
}

CLASSIFY_CASE = {
    "type": "function",
    "name": "classify_case",
    "description": "Call once you understand what the complaint is about. Returns the case type and confidence.",
    "parameters": {"type": "object", "properties": {}},
}


async def update_case_file(session, field: str, value: str):
    if field not in FIELDS:
        return {"error": f"unknown field, use one of {FIELDS}"}
    value = redact(value)
    session.fields[field] = value
    await insforge.upsert("case_fields", {"case_id": session.case_id, "field": field, "value": value,
                                          "updated_at": datetime.now(timezone.utc).isoformat()}, on_conflict="case_id,field")
    if field == "location":
        await insforge.update("cases", {"id": session.case_id}, {"location": value})
    await session.maybe_find_authorities()
    return {"saved": field}


async def flag_inconsistency(session, description: str):
    if description in session.conflicts:
        return {"recorded": True, "note": "already on the board"}
    session.conflicts.add(description)
    await insforge.insert("inconsistencies", {"case_id": session.case_id, "description": description})
    return {"recorded": True, "next": "Raise it kindly and ask which detail is right."}


async def classify_case(session):
    types = {k: f"{v['label']}: {v['signals']}" for k, v in ROUTING["case_types"].items()}
    out = await insforge.llm_json(
        f"Classify a complaint into exactly one case type. Types: {types}. "
        'Answer as JSON: {"case_type": "<key>", "confidence": <0 to 1>}',
        f"Case file: {session.fields}\nTranscript (English):\n{session.english_transcript()}")
    if out.get("case_type") not in ROUTING["case_types"]:
        return {"error": "could not classify yet, ask what happened"}
    session.case_type = out["case_type"]
    await insforge.update("cases", {"id": session.case_id},
                          {"case_type": out["case_type"], "confidence": out.get("confidence")})
    await session.maybe_find_authorities()
    label = ROUTING["case_types"][out["case_type"]]["label"]
    return {"case_type": out["case_type"], "label": label, "confidence": out.get("confidence")}
