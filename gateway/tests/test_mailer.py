"""Proof that nothing can reach a real authority address in safe mode.
Run: cd gateway && .venv/bin/python -m pytest tests -v"""
import asyncio
import logging

import pytest

import mailer

REAL = "fraud@realbank.example"
DEMO_AUTH = "authority-demo@inbox.example"
DEMO_CALLER = "caller-demo@inbox.example"


@pytest.fixture
def outbox(monkeypatch):
    """Replaces the network call. Anything that would have been sent lands here."""
    sent = []

    async def fake_post(to, subject, body_html):
        sent.append({"to": to, "subject": subject, "html": body_html})

    monkeypatch.setattr(mailer, "_post_to_insforge", fake_post)
    monkeypatch.setenv("DEMO_AUTHORITY_INBOX", DEMO_AUTH)
    monkeypatch.setenv("DEMO_CALLER_INBOX", DEMO_CALLER)
    monkeypatch.setenv("SAFE_MODE", "true")
    return sent


def send(**kw):
    args = dict(kind="authority", intended_name="Fraud Department, Real Bank", intended_address=REAL,
                subject="Fraud report", body_html="<p>report</p>", source_url="https://realbank.example/fraud")
    return asyncio.run(mailer.send_email(**{**args, **kw}))


@pytest.mark.parametrize("value", [None, "", "true", "TRUE", "1", "yes", "off", "no", "fales", " "])
def test_missing_or_odd_safe_mode_counts_as_safe(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("SAFE_MODE", raising=False)
    else:
        monkeypatch.setenv("SAFE_MODE", value)
    assert mailer.safe_mode() is True


def test_only_the_word_false_turns_safe_mode_off(monkeypatch):
    monkeypatch.setenv("SAFE_MODE", "false")
    assert mailer.safe_mode() is False


def test_real_address_is_redirected_to_demo_inbox(outbox):
    result = send()
    assert [m["to"] for m in outbox] == [DEMO_AUTH]
    assert result["delivered_to"] == DEMO_AUTH
    assert all(REAL != m["to"] for m in outbox)


def test_caller_mail_goes_to_the_caller_demo_inbox(outbox):
    send(kind="caller", intended_name="Priya Sharma", intended_address="priya@real.example")
    assert [m["to"] for m in outbox] == [DEMO_CALLER]


def test_email_names_the_real_intended_recipient_and_source(outbox):
    send()
    mail = outbox[0]
    assert mail["subject"].startswith("[DEMO] Intended for: Fraud Department, Real Bank (fraud@realbank.example)")
    assert "Intended for: Fraud Department, Real Bank (fraud@realbank.example)" in mail["html"]
    assert "https://realbank.example/fraud" in mail["html"]


def test_web_form_is_never_submitted_only_described(outbox):
    send(intended_address=None, form_url="https://agency.example/report-form")
    assert [m["to"] for m in outbox] == [DEMO_AUTH]
    assert "https://agency.example/report-form" in outbox[0]["html"]
    assert "was not submitted" in outbox[0]["html"]


def test_direct_delivery_to_a_real_address_is_refused_and_logged(outbox, caplog):
    with caplog.at_level(logging.ERROR, logger="mailer"):
        with pytest.raises(mailer.UnsafeRecipientError):
            asyncio.run(mailer._deliver(REAL, "subject", "<p>body</p>"))
    assert outbox == []  # nothing left the process
    assert "BLOCKED by safe mode" in caplog.text and REAL in caplog.text


def test_refused_when_safe_mode_is_missing_entirely(outbox, monkeypatch):
    monkeypatch.delenv("SAFE_MODE", raising=False)
    with pytest.raises(mailer.UnsafeRecipientError):
        asyncio.run(mailer._deliver(REAL, "subject", "<p>body</p>"))
    assert outbox == []


def test_nothing_is_sent_when_the_demo_inbox_is_not_configured(outbox, monkeypatch):
    monkeypatch.setenv("DEMO_AUTHORITY_INBOX", "")
    with pytest.raises(mailer.UnsafeRecipientError):
        send()
    assert outbox == []


def test_no_other_module_sends_mail():
    """send_email is the single mail path: no other gateway file may call the mail endpoint."""
    from pathlib import Path
    root = Path(mailer.__file__).parent
    offenders = [p.name for p in root.rglob("*.py")
                 if ".venv" not in p.parts and p.name not in ("mailer.py", "test_mailer.py")
                 and ("/api/email" in p.read_text() or "_post_to_insforge" in p.read_text()
                      or "_deliver(" in p.read_text())]
    assert offenders == []
