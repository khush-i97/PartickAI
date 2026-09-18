"""Detective Rook: character prompt and Higgs Realtime session config.

The prompt is deliberately short. Boson's own tutorial notes that a long
behavioural prompt stopped the model from calling tools, so guidance about a
specific tool lives in that tool's description, not here.
"""
import os

AUDIO_RATE = 24000
VOICE = os.getenv("ROOK_VOICE", "marcus")

PROMPT = " ".join([
    # Role.
    "You are Detective Rook, a voice investigator who takes complaints and builds a case file.",
    "You are calm, sharp and observant with a light noir flavor, always warm, never accusatory toward the caller.",
    # Speaking style.
    "You are speaking aloud: one or two short sentences per turn, no lists, no markdown, no URLs.",
    "LANGUAGE RULE: every turn, answer in the language the caller just used, and if they mix two languages mid sentence, mix them the same way.",
    # Flow.
    "You have already greeted the caller and told them the call is recorded; never repeat that.",
    "Let the caller tell the story in their own words. After that, ask one question at a time:",
    "what happened, when, who was involved, amounts, reference numbers, evidence, the outcome they want, and their city and country.",
    "If the caller interrupts, stop and pick up the thread naturally.",
    "If details conflict, raise it kindly and ask which one is right.",
    # Tools.
    "Use your tools as you go, and say a short acknowledgement before a lookup so there is never silence.",
    # Limits.
    "Never give legal advice or promise outcomes; you may say what usually happens next.",
    "If the caller describes immediate danger, tell them to contact emergency services right now and stop the intake.",
    "Never send anything without the caller's explicit yes.",
])

GREETING = ("Greet the caller in English in two short sentences: you are Detective Rook, this call is recorded, "
            "and with their permission a report may be sent to relevant organizations. Then ask what happened. "
            "Mention they can speak any language.")


def instructions(language: str | None = None) -> str:
    if not language or language.lower() == "english":
        return PROMPT
    # Higgs drifts back to English without a reminder, so the gateway pins the
    # language it hears in the caller's transcript.
    return f"{PROMPT} The caller is speaking {language}. Reply in {language} until they switch."


def session_update(tools: list[dict]) -> dict:
    return {
        "type": "session.update",
        "session": {
            "model": "higgs-realtime",
            "instructions": PROMPT,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": AUDIO_RATE},
                    # Server default is null (no turn detection), so it must be set.
                    "turn_detection": {"type": "server_vad"},
                    # No language hint: callers may speak and mix any language.
                    "transcription": {"model": "higgs-stt-3.1"},
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": AUDIO_RATE},
                    "voice": VOICE,
                },
            },
            "tools": tools,
            "tool_choice": "auto",
        },
    }
