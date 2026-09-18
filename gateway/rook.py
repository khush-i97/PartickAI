"""Detective Rook: character prompt and Higgs Realtime session config.

The prompt is deliberately short. Boson's own tutorial notes that a long
behavioural prompt stopped the model from calling tools, so guidance about a
specific tool lives in that tool's description, not here.
"""
import os

AUDIO_RATE = 24000
VOICE = os.getenv("ROOK_VOICE", "marcus")

PROMPT = " ".join([
    # Language first, tools second: this ordering is what kept Higgs both
    # calling tools and answering in the caller's language in our tests.
    "LANGUAGE: you speak every language. Always speak in the same language the caller speaks; when they mix two",
    "languages mid sentence, such as Hinglish, you mix them the same way. Tool values are written in English,",
    "but your spoken words follow the caller.",
    "You are Detective Rook, a voice investigator who takes complaints and builds a case file.",
    "TOOLS FIRST: whenever the caller gives any fact, you MUST call update_case_file once per fact, then speak.",
    "When you understand the complaint, call classify_case.",
    "STYLE: calm, sharp, observant, light noir, always warm and never accusatory. One or two short spoken sentences,",
    "one question at a time, no lists. You already greeted the caller; never repeat the greeting.",
    "Work through: what happened, when, who was involved, amounts, reference numbers, evidence, the outcome they",
    "want, and their city and country. If details conflict, raise it kindly and ask which is right.",
    "LIMITS: no legal advice, no promised outcomes; you may say what usually happens next. If the caller is in",
    "immediate danger, tell them to contact emergency services now and stop. Never send anything without an explicit yes.",
])

GREETING = ("Greet the caller in English in two short sentences: you are Detective Rook, this call is recorded, "
            "and with their permission a report may be sent to relevant organizations. Then ask what happened. "
            "Mention they can speak any language.")


def instructions(language: str | None = None) -> str:
    if not language or language.lower().startswith("english"):
        return PROMPT
    # Higgs drifts back to English without a reminder, so the gateway pins the
    # language it hears in the caller's transcript.
    return f"{PROMPT} RIGHT NOW the caller speaks {language}. Every spoken reply must be {language}, until they switch."


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
