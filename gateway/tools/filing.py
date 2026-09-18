"""End of the call: propose, file only after an explicit yes, confirm.

Approval is enforced here, in code. file_case refuses unless propose_filing
ran first, accepts only destinations that were proposed, and asks the Model
Gateway to confirm the caller really said yes (and which offices they removed)
from the transcript, so a voice model slip cannot send anything."""
import asyncio
import html
import json
import logging
import time
from datetime import datetime, timezone

import insforge
import mailer
from redact import redact
from .case_file import ROUTING

log = logging.getLogger("filing")

PROPOSE_FILING = {
    "type": "function",
    "name": "propose_filing",
    "description": ("Call when the caller signals they are done (for example 'okay, that's all, thank you', in any "
                    "language). Returns the case summary and the organizations you plan to contact. Read the summary "
                    "back briefly, name each organization and why, say nothing is sent yet, and ask for approval. "
                    "The caller may remove any organization."),
    "parameters": {"type": "object", "properties": {}},
}

FILE_CASE = {
    "type": "function",
    "name": "file_case",
    "description": ("Send the reports. Call ONLY after the caller has explicitly said yes to your proposal. "
                    "List only the organizations the caller approved; leave out any they removed."),
    "parameters": {"type": "object", "required": ["approved_destinations"], "properties": {
        "approved_destinations": {"type": "array", "items": {"type": "string"},
                                  "description": "Names of the approved organizations, as proposed."}}},
}

SEND_CONFIRMATION = {
    "type": "function",
    "name": "send_confirmation",
    "description": "After the reports are sent, email the caller a confirmation with every destination and the transcript.",
    "parameters": {"type": "object", "properties": {}},
}

EMERGENCY_STOP = {
    "type": "function",
    "name": "emergency_stop",
    "description": ("Call if the caller describes immediate danger to anyone. Then tell them to contact emergency "
                    "services right now and stop the intake. Nothing can be filed afterwards."),
    "parameters": {"type": "object", "required": ["reason"], "properties": {"reason": {"type": "string"}}},
}


async def emergency_stop(session, reason: str):
    session.emergency = True
    await insforge.update("cases", {"id": session.case_id}, {"emergency": True, "status": "emergency"})
    return {"stopped": True, "next": "Tell the caller to contact emergency services right now. Do not continue the intake."}


async def propose_filing(session):
    if session.emergency:
        return {"error": "Intake was stopped for an emergency. Nothing can be filed."}
    planned = [a for a in session.authorities.values() if a["approval"] != "removed"]
    if not planned:
        return {"error": "No organizations found yet. Make sure the case type and the caller's city are known, "
                         "then tell the caller you are still looking."}
    out = await insforge.llm_json(
        "Summarize this complaint for the caller to confirm, in three short English sentences, facts only. "
        'Answer as JSON: {"summary": "..."}',
        f"Case file: {session.fields}\nTranscript:\n{session.english_transcript()}")
    session.summary = out.get("summary", "")
    session.proposed_at_turn = len(session.turns)
    await insforge.update("cases", {"id": session.case_id}, {
        "status": "proposed", "summary": session.summary, "proposed_at": datetime.now(timezone.utc).isoformat()})
    return {"summary": session.summary, "nothing_sent_yet": True,
            "planned_organizations": [{"name": a["name"], "why": a["reason"]} for a in planned],
            "next": "Read this back briefly in the caller's language, then ask: shall I send these? "
                    "They can remove any of them."}


async def file_case(session, approved_destinations: list[str]):
    if session.emergency:
        return {"error": "Intake was stopped for an emergency. Nothing can be filed."}
    if session.proposed_at_turn is None:
        return {"error": "Call propose_filing first and get an explicit yes from the caller."}
    if session.filed:
        return {"error": "This case was already filed."}

    proposed = [a for a in session.authorities.values() if a["approval"] != "removed"]
    heard = await heard_approval(session, [a["name"] for a in proposed])
    if not heard.get("approved"):
        return {"error": "The caller has not clearly said yes yet. Ask them plainly whether to send the reports."}

    wanted = [d.lower() for d in approved_destinations]
    removed = [r.lower() for r in heard.get("removed", [])]
    approved = []
    for a in proposed:
        name = a["name"].lower()
        named_by_patrick = any(w in name or name in w or w == a["role"] for w in wanted)
        removed_by_caller = any(r in name or name in r for r in removed)
        ok = named_by_patrick and not removed_by_caller
        a["approval"] = "approved" if ok else "removed"
        await insforge.update("authorities", {"id": a["id"]}, {"approval": a["approval"]})
        if ok:
            approved.append(a)
    if not approved:
        await insforge.update("cases", {"id": session.case_id}, {"status": "declined"})
        return {"sent": [], "note": "Nothing was approved, so nothing was sent. Tell the caller that."}

    session.filed = True
    await insforge.update("cases", {"id": session.case_id}, {
        "status": "filed", "approved_at": datetime.now(timezone.utc).isoformat()})
    session.spawn(send_reports(session, approved))
    return {"sending_to": [a["name"] for a in approved], "not_sending_to": [a["name"] for a in proposed if a not in approved],
            "next": "Tell the caller the reports are going out now and what usually happens next. No promises."}


async def heard_approval(session, names: list[str]) -> dict:
    # Caller transcripts arrive late and grow in pieces. Wait until the answer
    # has settled, or a half transcribed "yes, but not the police" could lose its second half.
    for _ in range(16):
        since = list(session.turns.values())[session.proposed_at_turn:]
        settled = time.monotonic() - session.last_caller_text_at > 1.5 and not session.user_speaking
        if settled and any(t["speaker"] == "caller" for t in since):
            break
        await asyncio.sleep(0.5)
    said = "\n".join(f"{t['speaker']}: {t.get('english') or t['text']}" for t in since)
    return await insforge.llm_json(
        "An agent proposed sending reports to some organizations and asked the caller for approval. From the "
        "conversation after the proposal, decide whether the caller explicitly said yes to sending, and which "
        "organizations they asked to remove. If they said no, or did not answer, approved is false. "
        f'Organizations: {names}. Answer as JSON: {{"approved": true|false, "removed": ["exact names"]}}',
        said or "(the caller has said nothing since the proposal)")


async def transcript_url(session) -> str:
    if not session.transcript_link:
        rows = "".join(
            f"<p><b>{html.escape(t['speaker'].title())}:</b> {html.escape(t['text'])}"
            + (f"<br><i>{html.escape(t['english'])}</i>" if t.get("english") and t["english"] != t["text"] else "")
            + "</p>" for t in session.turns.values())
        page = f"<meta charset='utf-8'><h2>Call transcript, case {session.case_id}</h2>" \
               f"<p>Original language with English translation. Card numbers and passwords are redacted.</p>{rows}"
        session.transcript_html = page
        session.transcript_link = await insforge.upload(f"{session.case_id}/transcript.html", page.encode(), "text/html")
    return session.transcript_link


async def send_reports(session, approved: list[dict]):
    link = await transcript_url(session)
    needs = {d["role"]: d["needs"] for d in ROUTING["case_types"][session.case_type]["destinations"]}
    for n, a in enumerate(approved, 1):
        reference = f"CC-{session.case_id[:8].upper()}-{n}"
        row = await insforge.insert("dispatches", {
            "case_id": session.case_id, "authority_id": a["id"], "kind": "authority", "intended_name": a["name"],
            "intended_recipient": a["email"] or a["form_url"], "source_url": a["source_url"], "form_url": a["form_url"],
            "reference": reference, "status": "drafting"})
        try:
            draft = await insforge.llm_json(
                "Write a formal complaint report in English to the named organization, on behalf of the caller. "
                "Facts only, from the case file and transcript; never invent details; no legal conclusions. "
                "Cover the fields this organization needs, then a short timeline, then the outcome requested. "
                'Answer as JSON: {"subject": "...", "body_html": "<p>simple HTML paragraphs and lists</p>"}',
                f"Organization: {a['name']} ({a['handles']})\nNeeds: {needs.get(a['role'])}\nReference: {reference}\n"
                f"Case type: {session.case_type}\nCase file: {session.fields}\nSummary: {session.summary}\n"
                f"Transcript (English):\n{session.english_transcript()}")
            body = redact(draft["body_html"]) + (
                f"<hr><p>Reference: {reference}<br>Full transcript, original language with English: "
                f"<a href='{link}'>{link}</a></p>{session.transcript_html}")
            report_url = await insforge.upload(f"{session.case_id}/report-{a['role']}.html",
                                               ("<meta charset='utf-8'>" + body).encode(), "text/html")
            sent = await mailer.send_email(kind="authority", intended_name=a["name"], intended_address=a["email"],
                                           subject=redact(draft["subject"]), body_html=body,
                                           source_url=a["source_url"], form_url=a["form_url"])
            patch = {"status": "sent", "delivered_to": sent["delivered_to"], "subject": sent["subject"],
                     "body_html": sent["body_html"], "report_url": report_url}
        except mailer.UnsafeRecipientError as e:
            patch = {"status": "blocked", "error": str(e)}
        except Exception as e:
            log.exception("dispatch failed")
            patch = {"status": "failed", "error": str(e)[:300]}
        patch["updated_at"] = datetime.now(timezone.utc).isoformat()
        session.dispatches.append({**row, **patch})
        await insforge.update("dispatches", {"id": row["id"]}, patch)

    ok = [d["intended_name"] for d in session.dispatches if d["status"] == "sent"]
    bad = [d["intended_name"] for d in session.dispatches if d["status"] != "sent"]
    await session.note(f"Reports sent for: {ok or 'none'}. Could not send: {bad or 'none'}. Tell the caller what was "
                       "sent and what usually happens next, then call send_confirmation.")
    await session.invoke("send_confirmation", {}, source="backup")


async def send_confirmation(session):
    if session.confirmed:
        return {"sent": True, "note": "The confirmation was already sent."}
    if not session.dispatches:
        return {"error": "Nothing has been filed yet."}
    session.confirmed = True
    link = await transcript_url(session)
    items = "".join(
        f"<li><b>{html.escape(d['intended_name'])}</b>: {html.escape(d['status'])}, reference {d['reference']}"
        f"{', web form ' + html.escape(d['form_url']) if d.get('form_url') else ''}</li>" for d in session.dispatches)
    body = (f"<p>Hello {html.escape(session.fields.get('caller_name', ''))},</p>"
            f"<p>This confirms what Detective Patrick filed for you.</p><p>{html.escape(session.summary)}</p>"
            f"<ul>{items}</ul><p>What usually happens next: each organization reviews the report and may contact you "
            f"for more detail. This is not legal advice and no outcome is promised.</p>"
            f"<p>Transcript: <a href='{link}'>{link}</a></p>{session.transcript_html}")
    row = await insforge.insert("dispatches", {
        "case_id": session.case_id, "kind": "caller", "intended_name": session.fields.get("caller_name", "Caller"),
        "intended_recipient": session.fields.get("caller_email"), "status": "drafting"})
    try:
        sent = await mailer.send_email(kind="caller", intended_name=session.fields.get("caller_name", "Caller"),
                                       intended_address=session.fields.get("caller_email"),
                                       subject=f"Your case {session.case_id[:8].upper()} was filed", body_html=body)
        patch = {"status": "sent", "delivered_to": sent["delivered_to"], "subject": sent["subject"],
                 "body_html": sent["body_html"]}
    except Exception as e:
        patch = {"status": "blocked" if isinstance(e, mailer.UnsafeRecipientError) else "failed", "error": str(e)[:300]}
    await insforge.update("dispatches", {"id": row["id"]}, patch)
    return {"sent": patch["status"] == "sent", "status": patch["status"]}
