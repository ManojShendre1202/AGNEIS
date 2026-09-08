"""Maps a workflow stage name (sent over TCP from backend/core, fire-and-forget)
to the callable that runs it. tcp_server.py resolves these dynamically via
importlib so the dispatcher itself never hardcodes stage logic.

Format: "dotted.module.path:function_name". Each handler takes task_spec_id
plus whatever extra kwargs the TCP payload carried (see tcp_server.py),
and returns a JSON-serializable dict, which tcp_server._run_job merges into
the "stage_complete" websocket message.

"negotiate" runs the LangGraph agent pipeline (backend/agnies/negotiation/)
to completion in prod mode, or exactly one paused step in dev mode (mode=
"dev"|"prod" kwarg). "negotiate_step" advances a dev-mode run that's
currently paused, by exactly one more step.
"""

STAGE_HANDLERS = {
    "extract": "backend.agnies.roster_creation.extract_task_spec:run_extract",
    "roster": "backend.agnies.roster_creation.prime_bootstrap:run_roster",
    "negotiate": "backend.agnies.negotiation.negotiation_graph:run_negotiate",
    "negotiate_step": "backend.agnies.negotiation.negotiation_graph:run_negotiate_step",
}
