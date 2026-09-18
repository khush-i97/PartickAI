"""lookup_transactions: mock bank data for scam cases (db/003_seed_mock_bank.sql)."""
import re
from datetime import datetime

import insforge

LOOKUP_TRANSACTIONS = {
    "type": "function",
    "name": "lookup_transactions",
    "description": ("In a scam or fraud case, check the caller's recent bank transactions once you know the last "
                    "four digits of the account. Compare the dates, days and amounts with what the caller said. "
                    "If anything differs, call flag_inconsistency."),
    "parameters": {"type": "object", "required": ["account_hint"], "properties": {
        "account_hint": {"type": "string", "description": "Last four digits of the account."},
        "date_range": {"type": "string", "description": "Optional, for example 'last 7 days'."}}},
}


async def lookup_transactions(session, account_hint: str, date_range: str = ""):
    last4 = re.sub(r"\D", "", account_hint)[-4:]
    session.lookups.add(last4)
    accounts = await insforge.select("mock_accounts", account_hint=f"eq.{last4}")
    if not accounts:
        return {"found": False, "note": "No account ends in those digits. Ask the caller to check the number."}
    account = accounts[0]
    rows = await insforge.select("mock_transactions", account_id=f"eq.{account['id']}",
                                 order="posted_at.desc", limit=10)
    txns = []
    for r in rows:
        when = datetime.fromisoformat(r["posted_at"].replace("Z", "+00:00"))
        txns.append({"day": when.strftime("%A"), "date": when.strftime("%d %B %Y"), "time": when.strftime("%H:%M"),
                     "amount": f"{r['amount']} {r['currency']}", "direction": r["direction"],
                     "to_or_from": r["counterparty"], "reference": r["reference"], "note": r["description"]})
    result = {"found": True, "bank": account["bank_name"], "holder": account["holder_name"], "transactions": txns}
    if conflict := await find_conflict(session, txns):
        result["conflict"] = conflict
        result["next"] = ("This conflict is already recorded on the board, do not flag it again. "
                          "Raise it kindly with the caller and ask which detail is right.")
    return result


async def find_conflict(session, txns: list[dict]) -> str | None:
    """Compare the caller's account with the bank record. The check runs here,
    in code, so the planted mismatch is caught even if the voice model skims."""
    out = await insforge.llm_json(
        "Compare what a caller said with their bank transactions. Find the transaction they are describing. "
        "If the day, date or amount they stated differs from that record, describe the conflict in one English "
        'sentence naming both values. Answer as JSON: {"conflict": "<sentence>" or null}',
        f"Caller said: {session.fields}\nTranscript:\n{session.english_transcript()}\nTransactions: {txns}")
    conflict = out.get("conflict")
    if conflict and conflict not in session.conflicts:
        await session.invoke("flag_inconsistency", {"description": conflict}, source="backup")
    return conflict
