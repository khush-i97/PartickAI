"""Redact card numbers and passwords the caller says out loud.
Applied before anything is stored, shown, or emailed. Best effort: spoken
digits ("four five one two...") are not caught, only digits in the transcript."""
import re

CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
# A secret word only counts when it is followed by "is", ":" or the like, so that
# ordinary speech such as "pin down the timing" is left alone.
SECRET = re.compile(
    r"((?:password|passcode|pass code|pin|cvv|otp|पासवर्ड|contraseña)\s*(?:is|was|hai|tha|है|था|es|:|=)\s*)(\S+)",
    re.IGNORECASE)


def _mask_card(m: re.Match) -> str:
    digits = re.sub(r"\D", "", m.group())
    return f"[card ending {digits[-4:]}]"


def redact(text: str) -> str:
    text = CARD.sub(_mask_card, text)
    return SECRET.sub(lambda m: m.group(1) + "[redacted]", text)
