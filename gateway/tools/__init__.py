"""Tool registry for the voice agent.

TOOLS is the JSON schema list sent to Higgs Realtime in session.update.
HANDLERS maps each tool name to an async function(session, **args).
Tools are added milestone by milestone.
"""
TOOLS: list[dict] = []
HANDLERS: dict = {}
