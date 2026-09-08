from typing import Optional, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph

from backend.core.services.negotiation_turn_service import NegotiationTurnService
from workflow import ws_server

from .agent_shell import save_resolved_fact
from .config import (
    REFLECT_INSTRUCTION,
    ROLE_TURN_CONTINUE_INSTRUCTION,
    ROLE_TURN_INITIAL_INSTRUCTION,
)
from .ownership import check_verification, load_full_roster, owning_roles_for_path
from .prime import is_fact_request, prime_resolve_fact, prime_resolve_routing
from .review import run_close_review
from .roles import (
    conversation_entry_text,
    execute_tool_calls,
    format_tool_results,
    has_reportable_tool_results,
    run_role,
    update_open_tool_errors,
)


class GraphState(TypedDict):
    task_spec_id: int
    api_key: str
    task_spec: dict
    roster: list[dict]
    full_roster: list[dict]
    known_roles: list[str]
    current_role: Optional[str]
    turn: int
    max_turns: int
    conversation: str
    last_result: dict
    done: bool
    pending_prime: Optional[dict]
    queue: list[str]
    pending_asks: dict
    reflected: bool
    last_executed: list[dict]
    protected_paths: list[str]
    current_node_id: Optional[int]
    current_node_role: Optional[str]
    next_parent_node_id: Optional[int]
    queue_parents: dict
    pending_prime_parent_node_id: Optional[int]
    pending_close_review: bool
    last_tool_failure: Optional[str]
    last_tool_results_text: Optional[str]
    open_tool_errors: dict
    call_counts: dict
    budget_escalated_roles: list[str]
    turn_cap_escalated: bool
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int


def _budget_for_role(full_roster: list[dict], role_name: str) -> Optional[int]:
    for entry in full_roster:
        if entry["role_name"] == role_name:
            return entry.get("budget_calls")
    return None


def _accumulate_tokens(state: GraphState, usage: dict) -> dict:
    """Fold one LLM call's usage into the run's running totals. Every node
    that makes an LLM call (role_turn, reflect, prime_resolve, close_review)
    goes through this so total_tokens is a real sum across the whole run, not
    just the per-turn role_turn/reflect calls."""
    usage = usage or {}
    return {
        "total_input_tokens": state.get("total_input_tokens", 0) + (usage.get("input_tokens") or 0),
        "total_output_tokens": state.get("total_output_tokens", 0) + (usage.get("output_tokens") or 0),
        "total_tokens": state.get("total_tokens", 0) + (usage.get("total_tokens") or 0),
    }


def _print_token_line(usage: dict) -> None:
    usage = usage or {}
    cache_read = usage.get("cache_read", 0)
    cache_creation = usage.get("cache_creation", 0)
    cache_note = f" (cache_read={cache_read} cache_creation={cache_creation})" if (cache_read or cache_creation) else ""
    print(f"    [TOKENS] input={usage.get('input_tokens', 0)} "
          f"output={usage.get('output_tokens', 0)} total={usage.get('total_tokens', 0)}{cache_note}")


def _sum_executor_usage(executed: list[dict]) -> dict:
    """write_file/edit_file each trigger a hidden executor LLM call (see
    executor.py's generate_file_content/generate_edit_patch) -- previously
    untracked entirely, so a turn writing several files silently cost real,
    uncounted tokens. Sums whatever `usage` dicts survived onto `executed`
    (read_file/list_dir/run_shell/install_package never carry one -- pure,
    no LLM involved -- so .get("usage") is None for those and they're
    skipped)."""
    total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
             "cache_read": 0, "cache_creation": 0}
    for e in executed:
        usage = e.get("usage")
        if not usage:
            continue
        for key in total:
            total[key] += usage.get(key) or 0
    return total


def _print_grand_total(state: GraphState) -> None:
    print("=" * 80)
    print(f"TOTAL TOKENS CONSUMED — input={state.get('total_input_tokens', 0)} "
          f"output={state.get('total_output_tokens', 0)} total={state.get('total_tokens', 0)}")
    print("=" * 80)


def _turn_entry(turn: int, kind: str, result: dict) -> dict:
    return {
        "turn": turn,
        "kind": kind,
        "response": result["response"],
        "tool_use": result["tool_use"],
        "addressed_to": result["addressed_to"],
        "requests_to_prime": result["requests_to_prime"],
        "stack_decisions": result["stack_decisions"],
        "interface_contracts": result["interface_contracts"],
    }


def role_turn_node(state: GraphState) -> dict:
    instruction = ROLE_TURN_INITIAL_INSTRUCTION if state["turn"] == 0 else ROLE_TURN_CONTINUE_INSTRUCTION

    pending_asks = dict(state.get("pending_asks") or {})
    own_asks = pending_asks.pop(state["current_role"], [])

    result = run_role(state["task_spec_id"], state["task_spec"], state["roster"],
                       state["api_key"], state["current_role"], instruction,
                       state["conversation"], state["turn"], pending_asks=own_asks,
                       tool_results_text=state.get("last_tool_results_text"),
                       open_tool_errors=state.get("open_tool_errors"))

    print("=" * 80)
    print(f"TURN {state['turn']} — {result['role_name']} ({result['model_tier']})")
    print("=" * 80)
    _print_token_line(result.get("usage"))
    print(result["response"])
    print()

    role_name = result["role_name"]
    parent_id = state.get("next_parent_node_id")
    merge = (
        parent_id is not None
        and parent_id == state.get("current_node_id")
        and state.get("current_node_role") == role_name
    )
    entry = _turn_entry(state["turn"], "turn", result)
    if merge:
        node_id = state["current_node_id"]
        NegotiationTurnService.append_entry(node_id, entry)
        ws_server.publish(state["task_spec_id"], {
            "type": "negotiate_node", "event": "continued", "node_id": node_id, "entry": entry,
        })
    else:
        node = NegotiationTurnService.create_node(
            state["task_spec_id"], parent_id, role_name, result["model_tier"], state["turn"], entry
        )
        node_id = node["id"]
        ws_server.publish(state["task_spec_id"], {"type": "negotiate_node", "event": "created", "node": node})

    entry_text = conversation_entry_text(result)
    conversation = (
        state["conversation"] + f"\n{result['role_name']}: {entry_text}\n"
        if entry_text else state["conversation"]
    )
    call_counts = dict(state.get("call_counts") or {})
    call_counts[role_name] = call_counts.get(role_name, 0) + 1
    return {
        "last_result": result,
        "conversation": conversation,
        "turn": state["turn"] + 1,
        "reflected": False,
        "current_node_id": node_id,
        "current_node_role": role_name,
        "next_parent_node_id": None,
        "call_counts": call_counts,
        "pending_asks": pending_asks,
        "last_tool_results_text": None,
        **_accumulate_tokens(state, result.get("usage")),
    }


def execute_tools_node(state: GraphState) -> dict:

    failure_context = state.get("last_tool_failure") or ""
    executed = execute_tool_calls(state["task_spec_id"], state["last_result"]["role_name"],
                                   state["last_result"]["tool_use"], failure_context,
                                   state["turn"] - 1, state["full_roster"], state["protected_paths"])

    full_roster = load_full_roster(state["task_spec_id"])
    if executed:
        NegotiationTurnService.append_tool_results(state["current_node_id"], executed)
        ws_server.publish(state["task_spec_id"], {
            "type": "negotiate_node", "event": "tool_results",
            "node_id": state["current_node_id"], "tool_results": executed,
        })

    run_or_install = [e for e in executed if e.get("kind") in ("run_shell", "install_package")]
    if run_or_install:
        last = run_or_install[-1]
        last_tool_failure = None if last.get("success", True) else format_tool_results([last])
    else:
        last_tool_failure = state.get("last_tool_failure")

    open_tool_errors = update_open_tool_errors(state.get("open_tool_errors") or {}, executed)

    last_tool_results_text = (
        format_tool_results(executed) if has_reportable_tool_results(executed) else None
    )

    executor_usage = _sum_executor_usage(executed)
    if executor_usage["total_tokens"]:
        file_calls = sum(1 for e in executed if e.get("usage"))
        print(f"    [EXECUTOR TOKENS] {file_calls} write_file/edit_file generation call(s):")
        _print_token_line(executor_usage)

    return {"last_executed": executed,
            "full_roster": full_roster, "last_tool_failure": last_tool_failure,
            "open_tool_errors": open_tool_errors,
            "last_tool_results_text": last_tool_results_text,
            **_accumulate_tokens(state, executor_usage)}


def route_after_execute_tools(state: GraphState) -> str:

    if state.get("reflected"):
        return "dispatch"
    if has_reportable_tool_results(state.get("last_executed", [])):
        return "reflect"
    return "dispatch"


def reflect_node(state: GraphState) -> dict:

    conversation = state["conversation"]

    result = run_role(state["task_spec_id"], state["task_spec"], state["roster"],
                       state["api_key"], state["current_role"], REFLECT_INSTRUCTION,
                       conversation, state["turn"],
                       tool_results_text=state.get("last_tool_results_text"),
                       open_tool_errors=state.get("open_tool_errors"))

    print("=" * 80)
    print(f"TURN {state['turn']} — {result['role_name']} (REFLECTION, {result['model_tier']})")
    print("=" * 80)
    _print_token_line(result.get("usage"))
    print(result["response"])
    print()

    pre_reflect = state["last_result"]
    known_pairs = {(a["role"], a["ask"]) for a in pre_reflect["addressed_to"]}
    merged_addressed_to = pre_reflect["addressed_to"] + [
        a for a in result["addressed_to"] if (a["role"], a["ask"]) not in known_pairs
    ]
    merged_requests = pre_reflect["requests_to_prime"] + result["requests_to_prime"]
    result = {**result, "addressed_to": merged_addressed_to, "requests_to_prime": merged_requests}

    reflect_entry_text = conversation_entry_text(result)
    new_conversation = (
        conversation + f"\n{result['role_name']} (reflection): {reflect_entry_text}\n"
        if reflect_entry_text else conversation
    )

    entry = _turn_entry(state["turn"], "reflect", result)
    NegotiationTurnService.append_entry(state["current_node_id"], entry)
    ws_server.publish(state["task_spec_id"], {
        "type": "negotiate_node", "event": "reflected", "node_id": state["current_node_id"], "entry": entry,
    })

    call_counts = dict(state.get("call_counts") or {})
    call_counts[result["role_name"]] = call_counts.get(result["role_name"], 0) + 1

    return {
        "last_result": result,
        "conversation": new_conversation,
        "turn": state["turn"] + 1,
        "reflected": True,
        "call_counts": call_counts,
        "last_tool_results_text": None,
        **_accumulate_tokens(state, result.get("usage")),
    }


def dispatch_node(state: GraphState) -> dict:

    result = state["last_result"]
    known_roles = set(state["known_roles"])
    queue = list(state["queue"])
    queue_parents = dict(state.get("queue_parents") or {})
    current_node_id = state["current_node_id"]
    pending_asks = {role: list(asks) for role, asks in (state.get("pending_asks") or {}).items()}

    for a in result["addressed_to"]:
        role = a["role"]
        if role not in known_roles or role == result["role_name"]:
            continue
        pending_asks.setdefault(role, []).append(
            {"from_role": result["role_name"], "ask": a["ask"], "turn": state["turn"] - 1}
        )
        if role not in queue:
            queue.append(role)
            queue_parents.setdefault(role, current_node_id)

    if result["requests_to_prime"]:
        req = result["requests_to_prime"][0]
        return {"pending_prime": {"what": req["what"], "why": req["why"], "from_role": result["role_name"]},
                "queue": queue, "queue_parents": queue_parents, "pending_asks": pending_asks,
                "pending_prime_parent_node_id": current_node_id}

    if queue:
        next_role = queue.pop(0)
        parent_id = queue_parents.pop(next_role, current_node_id)
        return {"current_role": next_role, "pending_prime": None, "queue": queue,
                "queue_parents": queue_parents, "pending_asks": pending_asks,
                "next_parent_node_id": parent_id}

    verification_steps = state["task_spec"].get("verification", [])
    if not verification_steps:

        return {"pending_prime": {
            "what": "GAP: this task has no verification steps defined — there is "
                    "nothing to check completion against",
            "why": "TaskSpec.verification is empty, so there is no deterministic way "
                   "to know when this project is actually done (extraction, stage 1, "
                   "never produced automatable pass/fail checks for it)",
            "from_role": result["role_name"],
        }, "queue": queue, "queue_parents": queue_parents, "pending_asks": pending_asks,
            "pending_prime_parent_node_id": current_node_id}

    unmet = check_verification(state["task_spec_id"], verification_steps)
    if not unmet:

        return {"pending_close_review": True, "queue": queue, "queue_parents": queue_parents,
                "pending_asks": pending_asks}

    budget_escalated_roles = list(state.get("budget_escalated_roles") or [])
    role_budget = _budget_for_role(state["full_roster"], result["role_name"])
    role_calls = (state.get("call_counts") or {}).get(result["role_name"], 0)
    if (role_budget is not None and role_calls >= role_budget
            and result["role_name"] not in budget_escalated_roles):
        budget_escalated_roles.append(result["role_name"])
        return {"pending_prime": {
            "what": f"GAP: role {result['role_name']} is over its call budget — continue or stop?",
            "why": f"{role_calls} LLM calls made against a budget_calls of {role_budget}",
            "from_role": result["role_name"],
        }, "queue": queue, "queue_parents": queue_parents, "pending_asks": pending_asks,
            "pending_prime_parent_node_id": current_node_id,
            "budget_escalated_roles": budget_escalated_roles}

    if state["turn"] >= state["max_turns"] and not state.get("turn_cap_escalated"):
        return {"pending_prime": {
            "what": "GAP: turn cap reached with no resolution",
            "why": f"{state['turn']} turns elapsed (cap was {state['max_turns']})",
            "from_role": result["role_name"],
        }, "queue": queue, "queue_parents": queue_parents, "pending_asks": pending_asks,
            "pending_prime_parent_node_id": current_node_id,
            "turn_cap_escalated": True}

    current_speaker_idle = not result["tool_use"]

    def owner_of(step: dict) -> str | None:
        owner_role = step.get("owner_role")
        if owner_role and owner_role in known_roles:
            return owner_role
        path = step.get("path")
        owners = owning_roles_for_path(state["full_roster"], path) if path else []
        return owners[0] if len(owners) == 1 else None

    for step in unmet:
        owner_role = owner_of(step)
        if owner_role is None:
            continue
        if current_speaker_idle and owner_role == result["role_name"]:
            continue
        return {"current_role": owner_role, "pending_prime": None, "queue": queue,
                "queue_parents": queue_parents, "pending_asks": pending_asks,
                "next_parent_node_id": current_node_id}

    return {"pending_prime": {
        "what": f"GAP: no dispatchable role for the {len(unmet)} unmet verification "
                f"step(s) — either ownership is ambiguous, or the only owner "
                f"({result['role_name']}) just reported nothing actionable",
        "why": f"unmet steps: {unmet}",
        "from_role": result["role_name"],
    }, "queue": queue, "queue_parents": queue_parents, "pending_asks": pending_asks,
        "pending_prime_parent_node_id": current_node_id}


def route_after_dispatch(state: GraphState) -> str:
    if state.get("done"):
        return END
    if state.get("pending_prime"):
        return "prime_resolve"
    if state.get("pending_close_review"):
        return "close_review"
    return "role_turn"


def close_review_node(state: GraphState) -> dict:
    verdict, usage = run_close_review(state["task_spec_id"], state["task_spec"], state["api_key"])
    token_update = _accumulate_tokens(state, usage)

    print("=" * 80)
    print("FINAL REVIEW")
    print("=" * 80)
    _print_token_line(usage)
    for f in verdict.findings:
        print(f"  [{'PASS' if f.passed else 'FAIL'}] {f.criterion}")
    print()

    entry = {
        "turn": state["turn"],
        "kind": "close_review",
        "findings": [f.model_dump() for f in verdict.findings],
        "all_passed": verdict.all_passed,
    }
    if state.get("current_node_id") is not None:
        NegotiationTurnService.append_entry(state["current_node_id"], entry)
    ws_server.publish(state["task_spec_id"], {
        "type": "negotiate_node", "event": "close_review", "entry": entry,
    })

    if verdict.all_passed:
        _print_grand_total({**state, **token_update})
        return {"done": True, "pending_close_review": False, **token_update}

    failing = [f for f in verdict.findings if not f.passed]
    feedback_text = "\n\n".join(
        ["--- FINAL REVIEW FOUND UNRESOLVED ISSUES ---"]
        + [f"FAILED: {f.criterion}\nEVIDENCE: {f.evidence}" for f in failing]
    )

    if state["turn"] >= state["max_turns"] and not state.get("turn_cap_escalated"):
        return {
            "pending_close_review": False,
            "pending_prime": {
                "what": "GAP: final review found unresolved failures at the turn cap",
                "why": feedback_text,
                "from_role": "FinalReview",
            },
            "pending_prime_parent_node_id": state.get("current_node_id"),
            "turn_cap_escalated": True,
            **token_update,
        }

    verification_steps = state["task_spec"].get("verification", [])

    def owner_of_criterion(criterion: str) -> str | None:
        for step in verification_steps:
            if step.get("kind") == "llm_review" and step.get("criterion") == criterion:
                owner = step.get("owner_role")
                return owner if owner in state["known_roles"] else None
        return None

    for finding in failing:
        owner_role = owner_of_criterion(finding.criterion)
        if owner_role:
            return {
                "pending_close_review": False,
                "current_role": owner_role,
                "conversation": state["conversation"] + f"\n{feedback_text}\n",
                "next_parent_node_id": state.get("current_node_id"),
                **token_update,
            }

    return {
        "pending_close_review": False,
        "pending_prime": {
            "what": f"GAP: final review found {len(failing)} failing criterion/criteria with "
                    f"no resolvable owner_role",
            "why": feedback_text,
            "from_role": "FinalReview",
        },
        "pending_prime_parent_node_id": state.get("current_node_id"),
        **token_update,
    }


def route_after_close_review(state: GraphState) -> str:
    if state.get("done"):
        return END
    if state.get("pending_prime"):
        return "prime_resolve"
    return "role_turn"


def prime_resolve_node(state: GraphState) -> dict:
    pending = state["pending_prime"]
    print(f"    [PRIME] resolving: {pending}")

    if is_fact_request(pending["what"]):
        topic = pending["what"].split(":", 1)[-1].strip() if ":" in pending["what"] else pending["what"]
        findings, sources, usage = prime_resolve_fact(state["api_key"], topic, pending["why"])
        print(f"    [PRIME] grounded search resolved ({len(sources)} sources): {findings[:200]}")
        _print_token_line(usage)

        save_resolved_fact(state["task_spec_id"], "Prime", topic, findings, "resolved",
                            "; ".join(sources) if sources else "grounded search, no citation returned")

        return {"current_role": pending["from_role"], "pending_prime": None,
                "next_parent_node_id": state.get("pending_prime_parent_node_id"),
                **_accumulate_tokens(state, usage)}

    decision, usage = prime_resolve_routing(state["api_key"], state["task_spec"], state["full_roster"],
                                             pending, state["conversation"])
    print(f"    [PRIME] routing decision: next_role={decision.next_role!r} — {decision.reasoning}")
    _print_token_line(usage)

    if decision.next_role and decision.next_role in state["known_roles"]:
        return {"current_role": decision.next_role, "pending_prime": None,
                "next_parent_node_id": state.get("pending_prime_parent_node_id"),
                **_accumulate_tokens(state, usage)}
    updated = _accumulate_tokens(state, usage)
    _print_grand_total({**state, **updated})
    return {"done": True, "pending_prime": None, **updated}


def route_after_prime(state: GraphState) -> str:
    return END if state.get("done") else "role_turn"


def build_graph(interrupt: bool = True):
    """interrupt=True (dev mode) pauses after every execute_tools node, so a
    caller advances exactly one step at a time via app.stream(None, config).
    interrupt=False (prod mode) runs straight through to END/turn-cap in one
    app.stream(initial_state, config) call."""
    graph = StateGraph(GraphState)
    graph.add_node("role_turn", role_turn_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("reflect", reflect_node)
    graph.add_node("dispatch", dispatch_node)
    graph.add_node("prime_resolve", prime_resolve_node)
    graph.add_node("close_review", close_review_node)

    graph.set_entry_point("role_turn")
    graph.add_edge("role_turn", "execute_tools")
    graph.add_conditional_edges("execute_tools", route_after_execute_tools)
    graph.add_edge("reflect", "execute_tools")
    graph.add_conditional_edges("dispatch", route_after_dispatch)
    graph.add_conditional_edges("prime_resolve", route_after_prime)
    graph.add_conditional_edges("close_review", route_after_close_review)

    checkpointer = InMemorySaver()
    interrupt_after = ["execute_tools"] if interrupt else []
    return graph.compile(checkpointer=checkpointer, interrupt_after=interrupt_after)
