import os
from pathlib import Path

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from backend.core.services.interface_contract_service import InterfaceContractService  # noqa: E402
from backend.core.services.negotiation_turn_service import NegotiationTurnService  # noqa: E402
from backend.core.services.resolved_fact_service import ResolvedFactService  # noqa: E402
from backend.core.services.role_activity_service import RoleActivityService  # noqa: E402
from backend.core.services.stack_decision_service import StackDecisionService  # noqa: E402
from backend.core.services.task_spec_service import TaskSpecService  # noqa: E402

from .agent_shell import load_roster_list, load_task_spec  # noqa: E402
from .config import DEFAULT_MAX_TURNS  # noqa: E402
from .executor import clear_sandbox_dir, seed_private_files, snapshot_existing_files  # noqa: E402
from .graph import GraphState, build_graph  # noqa: E402
from .ownership import ensure_verification_owners, load_full_roster  # noqa: E402

def reset_task_memory(task_spec_id: int) -> None:

    RoleActivityService.delete_for_task(task_spec_id)
    StackDecisionService.delete_for_task(task_spec_id)
    ResolvedFactService.delete_for_task(task_spec_id)
    InterfaceContractService.delete_for_task(task_spec_id)
    clear_sandbox_dir(task_spec_id)
    print(f"Reset role_activity/stack_decisions/resolved_facts/interface_contracts and wiped sandbox "
          f"for task_spec_id={task_spec_id}.")

_RUNS: dict[int, dict] = {}

def _prepare_run(task_spec_id: int, reset: bool, max_turns: int) -> tuple[GraphState, dict]:
    api_key = os.environ["GEMINI_KEY"]
    if reset:
        reset_task_memory(task_spec_id)
    NegotiationTurnService.delete_for_task(task_spec_id)

    task_spec = load_task_spec(task_spec_id)
    roster = load_roster_list(task_spec_id)
    full_roster = load_full_roster(task_spec_id)
    task_spec, backfill_usage = ensure_verification_owners(task_spec_id, task_spec, full_roster, api_key)
    if backfill_usage["total_tokens"]:
        print(f"    [TOKENS] verification-owner backfill: input={backfill_usage['input_tokens']} "
              f"output={backfill_usage['output_tokens']} total={backfill_usage['total_tokens']}")

    source_filename = TaskSpecService.get(task_spec_id).source_filename
    seeded = seed_private_files(task_spec_id, source_filename)
    if seeded:
        print(f"    [SEED] copied {len(seeded)} private file(s) from "
              f"planning/private_md/{Path(source_filename).stem}/: {seeded}")

    protected_paths = snapshot_existing_files(task_spec_id)
    initial_role = full_roster[0]["role_name"]

    initial_state: GraphState = {
        "task_spec_id": task_spec_id,
        "api_key": api_key,
        "task_spec": task_spec,
        "roster": roster,
        "full_roster": full_roster,
        "known_roles": [r["role_name"] for r in roster],
        "current_role": initial_role,
        "turn": 0,
        "max_turns": max_turns,
        "conversation": "",
        "last_result": {},
        "done": False,
        "pending_prime": None,
        "queue": [],
        "pending_asks": {},
        "reflected": False,
        "last_executed": [],
        "protected_paths": protected_paths,
        "current_node_id": None,
        "current_node_role": None,
        "next_parent_node_id": None,
        "queue_parents": {},
        "pending_prime_parent_node_id": None,
        "pending_close_review": False,
        "last_tool_failure": None,
        "last_tool_results_text": None,
        "open_tool_errors": {},
        "call_counts": {},
        "budget_escalated_roles": [],
        "turn_cap_escalated": False,
        "total_input_tokens": backfill_usage["input_tokens"],
        "total_output_tokens": backfill_usage["output_tokens"],
        "total_tokens": backfill_usage["total_tokens"],
    }
    config = {"configurable": {"thread_id": f"task_{task_spec_id}"}}
    return initial_state, config


def run_negotiate(task_spec_id: int, mode: str = "prod", reset: bool = False,
                   max_turns: int = DEFAULT_MAX_TURNS) -> dict:
    """mode="dev" pauses after the first step (role turn + tool execution);
    mode="prod" runs straight through to END/turn-cap in this one call."""
    TaskSpecService.mark_negotiating(task_spec_id, mode)
    initial_state, config = _prepare_run(task_spec_id, reset, max_turns)
    app = build_graph(interrupt=(mode == "dev"))
    _RUNS[task_spec_id] = {"app": app, "config": config}

    for _ in app.stream(initial_state, config, stream_mode="values"):
        pass

    snapshot = app.get_state(config)
    done = not snapshot.next
    if done:
        _RUNS.pop(task_spec_id, None)
        TaskSpecService.mark_negotiation_done(task_spec_id)
    return {"done": done, "waiting_for_step": mode == "dev" and not done}


def run_negotiate_step(task_spec_id: int) -> dict:
    """Advances a dev-mode run currently paused after its last step by
    exactly one more step."""
    run = _RUNS.get(task_spec_id)
    if run is None:
        raise RuntimeError(
            f"No paused negotiation run for task_spec_id={task_spec_id} — start one (mode=dev) first."
        )
    app, config = run["app"], run["config"]

    for _ in app.stream(None, config, stream_mode="values"):
        pass

    snapshot = app.get_state(config)
    done = not snapshot.next
    if done:
        _RUNS.pop(task_spec_id, None)
        TaskSpecService.mark_negotiation_done(task_spec_id)
    return {"done": done, "waiting_for_step": not done}
