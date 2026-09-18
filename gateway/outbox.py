"""The packet a caller would send: one drafted email per office, with the
transcript, the summary and the full details as real files beside it.

Built from the database rather than a live call session, so a finished case can
be reopened and reviewed. Nothing here sends: assembling the packet and putting
it in front of a person is deliberately separate from delivering it, and
delivery stays behind mailer.py's safe mode.
"""
import html as html_lib
import logging

from fpdf import FPDF

import insforge
import mailer
from redact import redact

log = logging.getLogger("outbox")

# PDF core fonts are Latin-1, and embedding a Unicode face costs about a
# megabyte per script. So the PDFs carry the English text, which is Latin by
# construction, and the caller's own words in their own script travel in the
# UTF-8 .txt beside them, where fonts do not apply.
SUBSTITUTES = {"₹": "INR ", "’": "'", "‘": "'", "“": '"', "”": '"',
               "–": "-", "—": "-", "…": "...", " ": " ", "€": "EUR ",
               "£": "GBP ", "•": "-"}


def _latin(text: str) -> str:
    for bad, good in SUBSTITUTES.items():
        text = text.replace(bad, good)
    # Anything still outside Latin-1 is a script this PDF cannot show; the .txt has it.
    return text.encode("latin-1", "replace").decode("latin-1")


INK = (26, 26, 28)
MUTED = (110, 110, 115)
ACCENT = (176, 124, 16)     # the app's desk-lamp amber, darkened to read on paper
STRIPE = (245, 243, 238)
RULE = (218, 214, 205)


class _Report(FPDF):
    """Something an office can file: a header it can identify at a glance, a
    footer that survives being printed and separated, and facts in a table
    rather than a wall of text."""

    def __init__(self, title: str, reference: str):
        super().__init__()
        self.doc_title, self.reference = title, reference
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(18, 16, 18)

    def header(self) -> None:
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*ACCENT)
        self.cell(0, 5, "PATRICK  ·  VOICE INTAKE", align="L")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"Reference {self.reference}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)
        self.set_font("Helvetica", "B", 17)
        self.set_text_color(*INK)
        self.multi_cell(0, 8, _latin(self.doc_title))
        self.set_draw_color(*ACCENT)
        self.set_line_width(0.8)
        y = self.get_y() + 1.5
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_y(y + 5)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y() - 2, self.w - self.r_margin, self.get_y() - 2)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f"Case {self.reference}  ·  prepared from a recorded call", align="L")
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    def section(self, heading: str) -> None:
        self.ln(3)
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, _latin(heading.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*RULE)
        self.set_line_width(0.2)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2.5)

    def paragraph(self, text: str, size: float = 10.5) -> None:
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "", size)
        self.set_text_color(*INK)
        self.multi_cell(0, 5.4, _latin(text))
        self.ln(1)

    def pairs(self, rows: list[tuple[str, str]]) -> None:
        """Label and value side by side, striped so a long list stays readable."""
        label_w = 46
        value_w = self.w - self.l_margin - self.r_margin - label_w
        for i, (label, value) in enumerate(rows):
            value = _latin(str(value or "-"))
            self.set_font("Helvetica", "", 10)
            lines = max(1, len(self.multi_cell(value_w, 5.2, value, dry_run=True, output="LINES")))
            height = lines * 5.2 + 2.4
            if self.get_y() + height > self.h - self.b_margin:
                self.add_page()
            if i % 2 == 0:
                self.set_fill_color(*STRIPE)
                self.rect(self.l_margin, self.get_y() - 0.6, label_w + value_w, height, style="F")
            top = self.get_y()
            self.set_xy(self.l_margin, top + 1)
            self.set_font("Helvetica", "B", 8.5)
            self.set_text_color(*MUTED)
            self.multi_cell(label_w, 5.2, _latin(str(label)).upper())
            self.set_xy(self.l_margin + label_w, top + 1)
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*INK)
            self.multi_cell(value_w, 5.2, value)
            self.set_y(top + height)

    def speech(self, speaker: str, said: str) -> None:
        """A transcript turn: who spoke, then what they said, indented."""
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "B", 8.5)
        self.set_text_color(*(ACCENT if speaker.lower().startswith("patrick") else MUTED))
        self.multi_cell(0, 4.6, _latin(speaker).upper())
        self.set_x(self.l_margin + 4)
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*INK)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 4, 5.2, _latin(said))
        self.ln(2)


def _pdf(title: str, blocks: list[tuple[str, str]], reference: str = "") -> bytes:
    """Plain text blocks, for documents that are prose rather than tables."""
    doc = _Report(title, reference)
    doc.add_page()
    for heading, body in blocks:
        if heading:
            doc.section(heading)
        if body:
            doc.paragraph(body)
    return bytes(doc.output())

LABELS = {
    "caller_name": "Caller", "caller_email": "Caller email", "what_happened": "What happened", "when": "When",
    "who_involved": "Who was involved", "amount": "Amount", "reference_numbers": "Reference numbers",
    "evidence": "Evidence", "desired_outcome": "Wants", "location": "Location", "address": "Address",
    "phone": "Phone", "date_of_birth": "Date of birth", "item_description": "Item", "place_lost": "Lost at",
    "bank_name": "Bank", "account_last4": "Account ending", "company_name": "Company",
    "property_manager": "Property manager",
}


def _esc(value) -> str:
    return html_lib.escape(str(value or ""))


async def build_packet(case_id: str) -> dict:
    """Everything the caller would send, drafted and stored. Safe to call twice:
    the files are written to the same keys and simply overwritten."""
    case = (await insforge.select("cases", id=f"eq.{case_id}") or [{}])[0]
    fields = await insforge.select("case_fields", case_id=f"eq.{case_id}")
    turns = await insforge.select("transcript_turns", case_id=f"eq.{case_id}")
    authorities = await insforge.select("authorities", case_id=f"eq.{case_id}")
    form_fields = await insforge.select("form_fields", case_id=f"eq.{case_id}")

    answers = {f["field"]: f["value"] for f in fields}
    turns = sorted(turns, key=lambda t: t.get("created_at") or "")
    live = [a for a in sorted(authorities, key=lambda a: a.get("rank") or 99) if a.get("approval") != "removed"]

    summary = await _summary(answers, turns)
    ref = case_id[:8].upper()
    facts = "\n".join(f"{LABELS.get(k, k)}: {v}" for k, v in answers.items())

    # PDFs are what an office expects an attached report to look like, and they
    # print and copy cleanly. The .txt exists because most of these offices take
    # a web form, and nobody can paste a PDF into a form field.
    documents = {
        "summary.pdf": ("application/pdf", _summary_pdf(ref, summary, answers)),
        "details.pdf": ("application/pdf", _details_pdf(ref, answers, form_fields, live)),
        "transcript.pdf": ("application/pdf", _transcript_pdf(ref, turns)),
        "answers.txt": ("text/plain; charset=utf-8", _answers_text(ref, summary, answers, form_fields, live).encode()),
    }
    files = {
        **{name: await _put(case_id, name, content_type, data)
           for name, (content_type, data) in documents.items()},
        # Kept for the in-app view links. Never attached: government mail filters
        # routinely quarantine .html attachments.
        "transcript.html": await _upload(case_id, "transcript.html", _transcript_html(case_id, turns)),
        "details.html": await _upload(case_id, "details.html", _details_html(case_id, answers, form_fields, live)),
    }

    sizes = {name: len(data) for name, (_type, data) in documents.items()}
    drafts = [_draft(a, case_id, summary, answers, form_fields, files, sizes) for a in live]
    return {"case_id": case_id, "case_type": case.get("case_type"), "summary": summary,
            "files": files, "documents": documents, "drafts": drafts}


async def send_draft(case_id: str, authority_id: str) -> dict:
    """Send one drafted email, with its files attached.

    Everything goes through mailer.send_email, so safe mode decides where it
    actually lands: with SAFE_MODE on, the real office is named in the subject
    and the message is redirected to the demo inbox. An office with no email
    address is not skipped here — in safe mode there is a real inbox to send to,
    and mailer refuses on its own once safe mode is off."""
    packet = await build_packet(case_id)
    draft = next((d for d in packet["drafts"] if d["authority_id"] == authority_id), None)
    if not draft:
        return {"error": "no draft for that office"}

    attachments = [{"name": name, "content_type": content_type, "content": data}
                   for name, (content_type, data) in packet["documents"].items()]
    row = await insforge.insert("dispatches", {
        "case_id": case_id, "authority_id": authority_id, "kind": "authority",
        "intended_name": draft["to_name"], "intended_recipient": draft["to_address"],
        "form_url": draft["form_url"], "source_url": draft["source_url"],
        "status": "drafting", "subject": draft["subject"]})
    try:
        sent = await mailer.send_email(
            kind="authority", intended_name=draft["to_name"], intended_address=draft["to_address"],
            subject=draft["subject"], body_html=draft["body_html"],
            source_url=draft["source_url"], form_url=draft["form_url"], attachments=attachments)
    except Exception as e:
        log.exception("sending to %s failed", draft["to_name"])
        await insforge.update("dispatches", {"id": row["id"]}, {"status": "failed", "error": str(e)[:400]})
        return {"status": "failed", "error": str(e)[:200]}

    await insforge.update("dispatches", {"id": row["id"]},
                          {"status": "sent", "delivered_to": sent["delivered_to"],
                           "subject": sent["subject"][:500], "body_html": sent["body_html"]})
    return {"status": "sent", "delivered_to": sent["delivered_to"], "attached": sent["attached"],
            "safe_mode": sent["safe_mode"], "intended_for": draft["to_name"]}


async def _summary(answers: dict, turns: list[dict]) -> str:
    """Three sentences a stranger in an office can act on."""
    if not answers and not turns:
        return ""
    transcript = "\n".join(f"{t['speaker']}: {t.get('english_text') or t.get('original_text') or ''}" for t in turns)
    try:
        out = await insforge.llm_json(
            "Summarize this complaint for the office that will receive it, in three short English sentences: what "
            "happened, when and where, and what the caller wants. Facts only, taken from the case file and the "
            "transcript. Never invent a detail, never add a legal conclusion. "
            'Answer as JSON: {"summary": "..."}',
            f"Case file: {answers}\nTranscript:\n{transcript[:6000]}")
        return redact(out.get("summary") or "")
    except Exception:
        log.exception("summary failed for the outbox packet")
        return ""


def _draft(authority: dict, case_id: str, summary: str, answers: dict, form_fields: list[dict],
           files: dict, sizes: dict) -> dict:
    """The email itself. Written from the case file rather than by a model, so
    the wording cannot drift into claims the caller never made."""
    reference = case_id[:8].upper()
    name = answers.get("caller_name") or "the caller"
    mine = [f for f in sorted(form_fields, key=lambda f: f.get("position") or 0)
            if f["authority_id"] == authority["id"]]
    missing = [f["label"] for f in mine if f.get("required") and not answers.get(f.get("maps_to") or "")]

    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(f['label'])}</td>"
        f"<td style='padding:4px 0'>{_esc(answers.get(f.get('maps_to') or '') or '—')}</td></tr>"
        for f in mine) or "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(LABELS.get(k, k))}</td>"
        f"<td style='padding:4px 0'>{_esc(v)}</td></tr>" for k, v in answers.items())

    body = (
        f"<p>Dear {_esc(authority['name'])},</p>"
        f"<p>I am writing to report the following. {_esc(summary)}</p>"
        f"<p>My details and the answers to your form are below. The full call transcript, a summary and the "
        f"complete case details are attached as PDFs, with a plain-text copy for your online form.</p>"
        f"<table style='border-collapse:collapse;font-size:14px'>{rows}</table>"
        f"<p>Please confirm receipt and let me know if anything further is needed.</p>"
        f"<p>Kind regards,<br>{_esc(name)}<br>Reference: {reference}</p>")

    return {
        "authority_id": authority["id"],
        "to_name": authority["name"],
        "to_address": authority.get("email"),
        "form_url": authority.get("form_url"),
        "source_url": authority.get("source_url"),
        "address": authority.get("address"),
        "subject": f"{_case_line(answers)} — report from {name} (ref {reference})",
        "body_html": redact(body),
        # PDFs and the plain-text answers travel with the email; the .html
        # versions are for viewing in the app only.
        "attachments": [{"name": k, "url": v, "bytes": sizes.get(k, 0)} for k, v in files.items()
                        if v and not k.endswith(".html")],
        "missing": missing,
        # No email address means a web form: those are never submitted for the caller.
        "sendable": bool(authority.get("email")),
    }


def _case_line(answers: dict) -> str:
    if item := answers.get("item_description"):
        return f"Lost or stolen property: {item}"
    return (answers.get("what_happened") or "Complaint")[:60]


def _summary_pdf(ref: str, summary: str, answers: dict) -> bytes:
    doc = _Report("Summary of the complaint", ref)
    doc.add_page()
    if summary:
        doc.paragraph(summary, size=11.5)
    doc.section("The case file")
    doc.pairs([(LABELS.get(k, k.replace("_", " ")), v) for k, v in answers.items()])
    doc.section("How this was recorded")
    doc.paragraph("The caller spoke to Detective Patrick, an automated voice intake service. Every fact above is "
                  "the caller's own statement, taken from the recorded call. The full transcript is attached.")
    return bytes(doc.output())


def _details_pdf(ref: str, answers: dict, form_fields: list[dict], authorities: list[dict]) -> bytes:
    doc = _Report("Case details", ref)
    doc.add_page()
    doc.section("Facts stated by the caller")
    doc.pairs([(LABELS.get(k, k.replace("_", " ")), v) for k, v in answers.items()])

    doc.section("Where this is being reported")
    for a in authorities:
        doc.set_x(doc.l_margin)
        doc.set_font("Helvetica", "B", 11)
        doc.set_text_color(*INK)
        doc.multi_cell(0, 5.6, _latin(a["name"]))
        doc.pairs([(k.replace("_", " "), a[k]) for k in ("address", "phone", "email", "form_url", "source_url")
                   if a.get(k)])
        doc.ln(2)

    for a in authorities:
        mine = [f for f in sorted(form_fields, key=lambda f: f.get("position") or 0) if f["authority_id"] == a["id"]]
        if mine:
            doc.section(f"{a['name']} — their form")
            doc.pairs([(f["label"], answers.get(f.get("maps_to") or "") or "still needed") for f in mine])
    return bytes(doc.output())


def _transcript_pdf(ref: str, turns: list[dict]) -> bytes:
    doc = _Report("Call transcript", ref)
    doc.add_page()
    doc.paragraph("The conversation in English. Where the caller spoke another language, their own words are in "
                  "the attached answers.txt, which keeps the original script.", size=9.5)
    doc.ln(2)
    if not turns:
        doc.paragraph("No transcript recorded.")
    for t in turns:
        said = t.get("english_text") or t.get("original_text") or ""
        if said.strip():
            speaker = t["speaker"] + (f" ({t['language']})" if t.get("language") else "")
            doc.speech(speaker, said)
    return bytes(doc.output())


def _detail_blocks(answers: dict, form_fields: list[dict], authorities: list[dict]) -> list[tuple[str, str]]:
    blocks = [("Facts", "\n".join(f"{LABELS.get(k, k)}: {v}" for k, v in answers.items()))]
    offices = []
    for a in authorities:
        line = [a["name"]]
        for key in ("address", "phone", "email", "form_url", "source_url"):
            if a.get(key):
                line.append(f"  {key.replace('_', ' ')}: {a[key]}")
        offices.append("\n".join(line))
    blocks.append(("Where this goes", "\n\n".join(offices)))
    for a in authorities:
        mine = [f for f in sorted(form_fields, key=lambda f: f.get("position") or 0) if f["authority_id"] == a["id"]]
        if mine:
            blocks.append((f"{a['name']} - form",
                           "\n".join(f"{f['label']}: {answers.get(f.get('maps_to') or '') or 'still needed'}"
                                     for f in mine)))
    return blocks


def _transcript_text(turns: list[dict], english_only: bool = False) -> str:
    out = []
    for t in turns:
        said = t.get("original_text") or ""
        english = t.get("english_text") or ""
        if english_only:
            out.append(f"{t['speaker']}: {english or said}")
        else:
            line = f"{t['speaker']}" + (f" ({t['language']})" if t.get("language") else "") + f": {said}"
            if english and english != said:
                line += f"\n    [English] {english}"
            out.append(line)
    return "\n\n".join(out) or "No transcript recorded."


def _answers_text(ref: str, summary: str, answers: dict, form_fields: list[dict], authorities: list[dict]) -> str:
    """Plain UTF-8, for pasting into the office's own web form. Keeps the
    caller's original wording, which the PDFs cannot always render."""
    parts = [f"CASE {ref}", "", summary, "", "YOUR DETAILS",
             "\n".join(f"{LABELS.get(k, k)}: {v}" for k, v in answers.items())]
    for a in authorities:
        mine = [f for f in sorted(form_fields, key=lambda f: f.get("position") or 0) if f["authority_id"] == a["id"]]
        if mine:
            parts += ["", f"{a['name'].upper()} - FORM ANSWERS",
                      "\n".join(f"{f['label']}\n  {answers.get(f.get('maps_to') or '') or '(still needed)'}"
                                for f in mine)]
    return "\n".join(parts)


def _transcript_html(case_id: str, turns: list[dict]) -> str:
    rows = "".join(
        f"<p><strong>{_esc(t['speaker'])}</strong>"
        f"{' · ' + _esc(t['language']) if t.get('language') else ''}<br>{_esc(t.get('original_text'))}"
        + (f"<br><em>{_esc(t['english_text'])}</em>" if t.get("english_text")
           and t.get("english_text") != t.get("original_text") else "") + "</p>"
        for t in turns)
    return _page(f"Call transcript — case {case_id[:8].upper()}", rows or "<p>No transcript recorded.</p>")


def _summary_html(case_id: str, summary: str, answers: dict) -> str:
    rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(LABELS.get(k, k))}</td>"
                   f"<td style='padding:4px 0'>{_esc(v)}</td></tr>" for k, v in answers.items())
    return _page(f"Summary — case {case_id[:8].upper()}",
                 f"<p>{_esc(summary)}</p><table style='border-collapse:collapse'>{rows}</table>")


def _details_html(case_id: str, answers: dict, form_fields: list[dict], authorities: list[dict]) -> str:
    facts = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(LABELS.get(k, k))}</td>"
                    f"<td style='padding:4px 0'>{_esc(v)}</td></tr>" for k, v in answers.items())
    offices = "".join(
        f"<li><strong>{_esc(a['name'])}</strong><br>{_esc(a.get('address'))}<br>"
        f"{_esc(a.get('phone'))} {_esc(a.get('email'))}<br>"
        f"<a href='{_esc(a.get('form_url') or a.get('source_url'))}'>{_esc(a.get('form_url') or a.get('source_url'))}</a></li>"
        for a in authorities)
    forms = ""
    for a in authorities:
        mine = [f for f in sorted(form_fields, key=lambda f: f.get("position") or 0) if f["authority_id"] == a["id"]]
        if not mine:
            continue
        rows = "".join(f"<tr><td style='padding:4px 12px 4px 0;color:#555'>{_esc(f['label'])}</td>"
                       f"<td style='padding:4px 0'>{_esc(answers.get(f.get('maps_to') or '') or 'still needed')}</td></tr>"
                       for f in mine)
        forms += f"<h3>{_esc(a['name'])} — form</h3><table style='border-collapse:collapse'>{rows}</table>"
    return _page(f"Case details — case {case_id[:8].upper()}",
                 f"<h3>Facts</h3><table style='border-collapse:collapse'>{facts}</table>"
                 f"<h3>Where this goes</h3><ul>{offices}</ul>{forms}")


def _page(title: str, body: str) -> str:
    return ("<meta charset='utf-8'><style>body{font:15px/1.5 -apple-system,Segoe UI,sans-serif;"
            f"max-width:44em;margin:2em auto;padding:0 1em}}</style><h2>{_esc(title)}</h2>{body}")


async def _upload(case_id: str, name: str, html: str) -> str | None:
    return await _put(case_id, name, "text/html", redact(html).encode())


async def _put(case_id: str, name: str, content_type: str, data: bytes) -> str | None:
    try:
        return await insforge.upload(f"{case_id}/{name}", data, content_type)
    except Exception:
        log.exception("could not store %s for case %s", name, case_id)
        return None
