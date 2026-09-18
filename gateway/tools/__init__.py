"""Tool registry for the voice agent.

TOOLS is the JSON schema list sent to Higgs Realtime in session.update.
HANDLERS maps each tool name to an async function(session, **args).
Guidance about a tool lives in its description, which keeps Patrick's prompt short.
"""
from . import authorities, bank, case_file, filing

TOOLS: list[dict] = [
    case_file.UPDATE_CASE_FILE,
    case_file.FLAG_INCONSISTENCY,
    case_file.CLASSIFY_CASE,
    bank.LOOKUP_TRANSACTIONS,
    authorities.FIND_AUTHORITIES,
    filing.PROPOSE_FILING,
    filing.FILE_CASE,
    filing.SEND_CONFIRMATION,
    filing.EMERGENCY_STOP,
]

HANDLERS: dict = {
    "update_case_file": case_file.update_case_file,
    "flag_inconsistency": case_file.flag_inconsistency,
    "classify_case": case_file.classify_case,
    "lookup_transactions": bank.lookup_transactions,
    "find_authorities": authorities.find_authorities,
    "propose_filing": filing.propose_filing,
    "file_case": filing.file_case,
    "send_confirmation": filing.send_confirmation,
    "emergency_stop": filing.emergency_stop,
}
