"""The only code path that sends email. Everything goes through send_email.

Safe mode is enforced here, in code, not in Patrick's prompt:
- SAFE_MODE missing, empty, or anything other than the word "false" means ON.
- In safe mode the real recipient is never mailed. Authority reports go to
  DEMO_AUTHORITY_INBOX and caller confirmations to DEMO_CALLER_INBOX.
- _deliver refuses any address that is not one of those two inboxes, logs the
  attempt, and raises instead of sending.
- Every email names the real intended recipient in the subject and at the top
  of the body, plus the source URL where that contact was found.
"""
import base64
import html as html_lib
import logging
import os

import httpx

log = logging.getLogger("mailer")


class UnsafeRecipientError(Exception):
    """Raised when safe mode is on and mail is addressed outside the demo inboxes."""


def safe_mode() -> bool:
    return os.getenv("SAFE_MODE", "").strip().lower() != "false"


def demo_inbox(kind: str) -> str:
    name = "DEMO_CALLER_INBOX" if kind == "caller" else "DEMO_AUTHORITY_INBOX"
    address = os.getenv(name, "").strip()
    if not address:
        raise UnsafeRecipientError(f"{name} is not set, so nothing can be sent in safe mode")
    return address


async def send_email(*, kind: str, intended_name: str, intended_address: str | None, subject: str, body_html: str,
                     source_url: str | None = None, form_url: str | None = None,
                     attachments: list[dict] | None = None) -> dict:
    """kind is 'authority' or 'caller'. intended_address is the real contact; in
    safe mode it is shown in the email but never mailed."""
    intended = f"{intended_name} ({intended_address or form_url or 'no direct address found'})"
    if safe_mode():
        to = demo_inbox(kind)
        subject = f"[DEMO] Intended for: {intended} | {subject}"
    elif intended_address:
        to = intended_address
    else:
        raise UnsafeRecipientError(f"{intended_name} has no email address; web forms are never submitted")

    banner = f"<p><strong>{'[DEMO] ' if safe_mode() else ''}Intended for: {html_lib.escape(intended)}</strong><br>"
    if form_url:
        banner += f"This organization takes reports through a web form: {html_lib.escape(form_url)}. "
        banner += "The form was not submitted; this email stands in for it.<br>"
    if source_url:
        banner += f"Contact found at: {html_lib.escape(source_url)}<br>"
    if safe_mode():
        banner += "Safe mode is on: this message was redirected to a demo inbox and was not sent to the organization."
    banner += "</p><hr>"

    full_html = banner + body_html
    await _deliver(to, subject[:500], full_html, attachments or [])
    return {"delivered_to": to, "subject": subject[:500], "body_html": full_html, "safe_mode": safe_mode(),
            "attached": [a["name"] for a in attachments or []]}


async def _deliver(to: str, subject: str, body_html: str, attachments: list[dict] | None = None) -> None:
    """Last gate before the network. Re-checks the address so that no future
    caller of this module can bypass safe mode. Attachments go through here too,
    so the file-carrying path cannot become a way around the check."""
    if safe_mode():
        allowed = {os.getenv("DEMO_AUTHORITY_INBOX", "").strip().lower(),
                   os.getenv("DEMO_CALLER_INBOX", "").strip().lower()} - {""}
        if to.strip().lower() not in allowed:
            log.error("BLOCKED by safe mode: attempted to send to %s (subject: %s)", to, subject)
            raise UnsafeRecipientError(f"safe mode is on, refusing to send to {to}")
    # Only AgentMail can carry files; without it the mail still goes, with the
    # documents as links in the body rather than attachments.
    if attachments and os.getenv("AGENTMAIL_API_KEY", "").strip():
        await _post_to_agentmail(to, subject, body_html, attachments)
    else:
        await _post_to_insforge(to, subject, body_html)


async def _post_to_agentmail(to: str, subject: str, body_html: str, attachments: list[dict]) -> None:
    """AgentMail, for mail that carries real files. InsForge's send-raw takes no
    attachments, which is the whole reason this exists.

    attachments: [{"name": "summary.pdf", "content_type": "application/pdf", "content": b"..."}]
    """
    key, inbox = os.environ["AGENTMAIL_API_KEY"], os.environ["AGENTMAIL_INBOX"]
    files = [{"filename": a["name"], "content_type": a.get("content_type", "application/octet-stream"),
              "content": base64.b64encode(a["content"]).decode()} for a in attachments]
    async with httpx.AsyncClient(timeout=90) as http:
        r = await http.post(f"https://api.agentmail.to/v0/inboxes/{inbox}/messages/send",
                            headers={"Authorization": f"Bearer {key}"},
                            json={"to": [to], "subject": subject, "html": body_html, "attachments": files})
        if r.status_code >= 400:
            log.error("AgentMail refused the send: %s %s", r.status_code, r.text[:300])
        r.raise_for_status()


async def _post_to_insforge(to: str, subject: str, body_html: str) -> None:
    """InsForge Messaging. Kept tiny so tests can replace it and prove nothing leaves."""
    async with httpx.AsyncClient(timeout=30) as http:
        r = await http.post(os.environ["INSFORGE_URL"].rstrip("/") + "/api/email/send-raw",
                            headers={"Authorization": f"Bearer {os.environ['INSFORGE_API_KEY']}"},
                            json={"to": [to], "subject": subject, "html": body_html, "from": "Detective Patrick"})
        r.raise_for_status()
