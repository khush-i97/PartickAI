"""Tool registry for the voice agent.

TOOLS is the JSON schema list sent to Higgs Realtime in session.update.
HANDLERS maps each tool name to an async function(session, **args).
Guidance about a tool lives in its description, which keeps Rook's prompt short.
"""
from . import bank, case_file

TOOLS: list[dict] = [
    case_file.UPDATE_CASE_FILE,
    case_file.FLAG_INCONSISTENCY,
    case_file.CLASSIFY_CASE,
    bank.LOOKUP_TRANSACTIONS,
]

HANDLERS: dict = {
    "update_case_file": case_file.update_case_file,
    "flag_inconsistency": case_file.flag_inconsistency,
    "classify_case": case_file.classify_case,
    "lookup_transactions": bank.lookup_transactions,
}
