"""One button that fills a case the way a real call would, without a microphone.

The conversation is canned; everything downstream of it is real. The offices are
found by live search, their forms are read from their own pages, and the packet
is drafted from what that search returns. A demo that faked the offices would
prove nothing about the part that actually has to work.
"""
import asyncio
import logging

import insforge
from tools import authorities, forms

log = logging.getLogger("demo")

# A caller who gives a campus rather than a city, which is the case the routing
# has to get right: ASU is Tempe, and nobody should have to be asked.
SCRIPT = [
    ("patrick", "Hi, this is Patrick. How can I help you today?", "English"),
    ("caller", "Hi, I lost my wallet walking from ASU to the bus stop.", "English"),
    ("patrick", "Oh no, that is a horrible feeling. When did you notice it was gone?", "English"),
    ("caller", "About three this afternoon, maybe an hour ago.", "English"),
    ("patrick", "Got it, around three today. What was in it?", "English"),
    ("caller", "Ten dollars, my student ID and my bank card.", "English"),
    ("patrick", "Thank you. And your name, so I can put it on the report?", "English"),
    ("caller", "Priya Sharma. My number is 602-555-0147.", "English"),
    ("patrick", "Thanks Priya. I am finding the right office for this now.", "English"),
]

FIELDS = {
    "caller_name": "Priya Sharma",
    "phone": "602-555-0147",
    "what_happened": "Lost a wallet walking from the ASU campus to the bus stop",
    "when": "Today, about 3pm",
    "item_description": "Brown leather wallet with ten dollars, a student ID and a bank card",
    "place_lost": "Arizona State University campus",
    "desired_outcome": "A lost property report so the wallet can be returned if handed in",
}


class _Seeded:
    """Enough of a call session for the real search code to run against."""

    def __init__(self, case_id: str, case_type: str, fields: dict):
        self.case_id, self.case_type, self.fields = case_id, case_type, fields
        self.searched_roles: set[str] = set()
        self.authorities: dict[str, dict] = {}
        self.asked_for: set[str] = set()
        self.searching = 0

    async def note(self, *_args, **_kwargs) -> None:
        """Notes are for the voice model, and there is no voice in a demo."""


async def seed() -> dict:
    """Build a finished-looking case. Returns its id for the board to open."""
    case = await insforge.insert("cases", {"status": "open"})
    case_id = case["id"]

    for speaker, text, language in SCRIPT:
        await insforge.insert("transcript_turns", {
            "case_id": case_id, "item_id": f"demo-{len(text)}-{speaker}-{SCRIPT.index((speaker, text, language))}",
            "speaker": speaker, "original_text": text, "english_text": text, "language": language})
    for field, value in FIELDS.items():
        await insforge.upsert("case_fields", {"case_id": case_id, "field": field, "value": value},
                              on_conflict="case_id,field")

    # The same resolution a call would do: a campus becomes a city, no question asked.
    city = await authorities.resolve_city(FIELDS["place_lost"], FIELDS["what_happened"]) or "Phoenix, Arizona"
    await insforge.upsert("case_fields", {"case_id": case_id, "field": "location", "value": city},
                          on_conflict="case_id,field")
    await insforge.update("cases", {"id": case_id},
                          {"case_type": "lost_property", "confidence": 0.97, "language": "English",
                           "location": city, "summary": "Wallet lost between the ASU campus and the bus stop."})

    session = _Seeded(case_id, "lost_property", {**FIELDS, "location": city})
    found = []
    for dest in authorities.ready_destinations(session):
        row = await authorities.search_destination(session, dest)
        if row:
            found.append(row)
    # Read each office's real form, so the board shows real questions.
    await asyncio.gather(*(forms.prepare_form(session, row) for row in found), return_exceptions=True)

    log.info("demo case %s seeded: %s, %d offices", case_id, city, len(found))
    return {"case_id": case_id, "location": city, "offices": [r["name"] for r in found]}
