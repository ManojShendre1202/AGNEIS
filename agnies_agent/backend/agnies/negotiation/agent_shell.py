from backend.agnies.schemas import RoleTurn
from backend.core.services.interface_contract_service import InterfaceContractService
from backend.core.services.resolved_fact_service import ResolvedFactService
from backend.core.services.role_activity_service import RoleActivityService
from backend.core.services.roster_entry_service import RosterEntryService
from backend.core.services.stack_decision_service import StackDecisionService
from backend.core.services.task_spec_service import TaskSpecService

from .config import AGENT_SHELL_EPHEMERAL, AGENT_SHELL_GROWING, AGENT_SHELL_STATIC
from .llm_factory import (
    bind_structured,
    build_chat_model,
    cached_system_block,
    parse_structured_result,
    supports_prompt_caching,
)
from .rate_limit import GEMINI_RATE_LIMITER, estimate_tokens
from .retry import call_with_retry


def extract_usage(raw_message) -> dict:
    """`input_tokens` already INCLUDES cache_read/cache_creation tokens (see
    langchain_anthropic._create_usage_metadata) -- a cache hit is billed at
    ~10% of normal price but still counted at full size in this total, so
    this number alone can't tell you whether caching is working. Surface
    `cache_read`/`cache_creation` separately so a caller can actually see
    the cache being hit, instead of mistaking the (expected, by-design)
    growth of the uncached GROWING+EPHEMERAL prompt tiers for a caching
    failure."""
    meta = getattr(raw_message, "usage_metadata", None) or {}
    details = meta.get("input_token_details") or {}
    # langchain_anthropic reports cache-creation tokens under the TTL-specific
    # key ("ephemeral_1h_input_tokens" here, since cached_system_block uses
    # ttl="1h") and zeroes out the generic "cache_creation" key whenever that
    # specific key is populated, to avoid double-counting -- reading only
    # "cache_creation" silently shows 0 even when a cache write just happened.
    cache_creation = (
        (details.get("cache_creation") or 0)
        + (details.get("ephemeral_5m_input_tokens") or 0)
        + (details.get("ephemeral_1h_input_tokens") or 0)
    )
    return {
        "input_tokens": meta.get("input_tokens") or 0,
        "output_tokens": meta.get("output_tokens") or 0,
        "total_tokens": meta.get("total_tokens") or 0,
        "cache_read": details.get("cache_read") or 0,
        "cache_creation": cache_creation,
    }


def _rate_limit_acquire(model_spec: str, prompt_for_estimate: str, label: str) -> None:
    # The free-tier RPM/TPM guard only applies to Gemini -- Anthropic/NVIDIA
    # calls here run on paid/stress-tested capacity that hasn't needed it.
    if model_spec.startswith("gemini:"):
        GEMINI_RATE_LIMITER.acquire(estimate_tokens(prompt_for_estimate), label=label)


def _rate_limit_record(model_spec: str, total_tokens: int) -> None:
    if model_spec.startswith("gemini:"):
        GEMINI_RATE_LIMITER.record(total_tokens)


def invoke_structured(model_spec: str, schema: type, prompt: str | list, label: str):
    """Generic single-prompt structured call -- every LLM call site that
    doesn't have a stable/growing prompt split (Prime routing, ownership
    backfill, close review, roster bootstrap, extraction) goes through this."""
    llm = build_chat_model(model_spec)
    structured_llm = bind_structured(llm, schema, model_spec)

    def _call():
        raw = structured_llm.invoke(prompt)
        return parse_structured_result(raw, schema, model_spec)

    _rate_limit_acquire(model_spec, prompt, label)
    parsed, raw_message = call_with_retry(_call, label=label)
    usage = extract_usage(raw_message)
    _rate_limit_record(model_spec, usage.get("total_tokens", 0))
    return parsed, usage


def invoke_role_turn(model_spec: str, static_prompt: str, dynamic_prompt: str, label: str):
    """Role-turn structured call, cache-aware: on a provider that supports
    prompt caching (Anthropic), the STATIC tier -- identical every turn for
    this role/task -- is sent as a cached system block, so every turn after
    the first pays full price only for the GROWING+EPHEMERAL tier instead of
    the whole prompt from scratch. On providers without caching wired up
    here, falls back to sending both tiers concatenated, same as before."""
    llm = build_chat_model(model_spec)
    structured_llm = bind_structured(llm, RoleTurn, model_spec)

    if supports_prompt_caching(model_spec):
        messages = [
            {"role": "system", "content": [cached_system_block(static_prompt)]},
            {"role": "user", "content": dynamic_prompt},
        ]
        prompt_for_estimate = static_prompt + dynamic_prompt

        def _call():
            raw = structured_llm.invoke(messages)
            return parse_structured_result(raw, RoleTurn, model_spec)
    else:
        prompt = static_prompt + dynamic_prompt
        prompt_for_estimate = prompt

        def _call():
            raw = structured_llm.invoke(prompt)
            return parse_structured_result(raw, RoleTurn, model_spec)

    _rate_limit_acquire(model_spec, prompt_for_estimate, label)
    parsed, raw_message = call_with_retry(_call, label=label)
    usage = extract_usage(raw_message)
    _rate_limit_record(model_spec, usage.get("total_tokens", 0))
    return parsed, usage


def load_task_spec(task_spec_id: int) -> dict:
    return TaskSpecService.get(task_spec_id).extracted_json


def load_role(task_spec_id: int, role_name: str) -> dict:
    return RosterEntryService.get_role(task_spec_id, role_name)


def load_roster_list(task_spec_id: int) -> list[dict]:
    return [
        {"role_name": r["role_name"], "mandate": r["mandate"]}
        for r in RosterEntryService.list_for_task(task_spec_id)
    ]


def format_roster_list(roster: list[dict], self_role_name: str) -> str:
    lines = []
    for r in roster:
        tag = " (you)" if r["role_name"] == self_role_name else ""
        lines.append(f"- {r['role_name']}{tag}: {r['mandate']}")
    return "\n".join(lines)


def format_pending_asks(asks: list[dict]) -> str:
    if not asks:
        return "(none — nobody has addressed you since your last turn)"
    lines = []
    for a in asks:
        turn = f" [turn {a['turn']}]" if a.get("turn") is not None else ""
        lines.append(f"- from {a['from_role']}{turn}: {a['ask']}")
    return "\n".join(lines)


def format_owned_paths(owned_paths: list[str]) -> str:
    if not owned_paths:
        return "(none — this role does not write to the sandbox filesystem)"
    return "\n".join(f"- {p}" for p in owned_paths)


def load_resolved_facts(task_spec_id: int) -> list[dict]:
    return ResolvedFactService.list_for_task(task_spec_id)


def format_resolved_facts(facts: list[dict]) -> str:
    if not facts:
        return "(none yet)"
    lines = []
    for f in facts:
        if f["status"] == "resolved":
            lines.append(f"- {f['topic']}: {f['value']} (source: {f['source']}, found for {f['resolved_by_role']})")
        else:
            lines.append(
                f"- {f['topic']}: CONFIRMED UNAVAILABLE (escalated to Prime, closed — "
                f"do not wait for this, plan around it now; originally raised by {f['resolved_by_role']})"
            )
    return "\n".join(lines)


def save_resolved_fact(task_spec_id: int, role_name: str, topic: str, value: str,
                        status: str, source: str) -> None:
    ResolvedFactService.create(task_spec_id, topic, value, status, source, role_name)


def load_stack_decisions(task_spec_id: int) -> list[dict]:
    return StackDecisionService.list_for_task(task_spec_id)


def format_stack_decisions(decisions: list[dict]) -> str:
    if not decisions:
        return "(none yet — first role to name a library/approach sets it)"
    lines = []
    for d in decisions:
        version = f" {d['version']}" if d["version"] else ""
        lines.append(f"- {d['package']}{version} (decided by {d['decided_by_role']}: {d['reasoning']})")
    return "\n".join(lines)


def save_stack_decision(task_spec_id: int, role_name: str, package: str,
                         version: str | None, reasoning: str) -> None:
    StackDecisionService.create(task_spec_id, package, version, role_name, reasoning)


def load_interface_contracts(task_spec_id: int) -> list[dict]:
    return InterfaceContractService.list_for_task(task_spec_id)


def format_interface_contracts(contracts: list[dict]) -> str:
    if not contracts:
        return "(none published yet — nothing is callable across roles so far)"
    lines = []
    for c in contracts:
        lines.append(
            f"- {c['signature']} — {c['description']} "
            f"(in {c['path']}, owned by {c['owner_role']})"
        )
    return "\n".join(lines)


def save_interface_contract(task_spec_id: int, role_name: str, path: str,
                             function_name: str, signature: str, description: str) -> None:
    InterfaceContractService.upsert(task_spec_id, role_name, path, function_name,
                                     signature, description)


def format_normative_spec_sections(sections: list[dict]) -> str:
    if not sections:
        return "(none for this task — no literal format/syntax/contract to match verbatim)"
    lines = []
    for s in sections:
        lines.append(f"--- {s['title']} ---\n{s['content']}")
    return "\n\n".join(lines)


def format_sandbox_files(paths: list[str]) -> str:
    if not paths:
        return "(empty — nothing has been written to the sandbox yet)"
    return "\n".join(f"- {p}" for p in paths)


def load_role_activity(task_spec_id: int, role_name: str) -> list[dict]:
    return RoleActivityService.list_for_task_and_role(task_spec_id, role_name)


def format_role_activity(activity: list[dict]) -> str:
    if not activity:
        return "(none yet — this is your first turn)"
    lines = []
    for a in activity:
        turn = f" [turn {a['turn']}]" if a["turn"] is not None else ""
        lines.append(f"- {a['action_type']}{turn}: {a['detail']}")
    return "\n".join(lines)


def save_role_activity(task_spec_id: int, role_name: str, action_type: str,
                        detail: str, turn: int | None = None) -> None:
    RoleActivityService.create(task_spec_id, role_name, action_type, detail, turn)


def _prompt_format_kwargs(role: dict, roster_list_text: str, resolved_facts_text: str, task_spec: dict,
                           conversation: str, instruction: str, sandbox_files_text: str,
                           stack_decisions_text: str, role_activity_text: str,
                           pending_asks_text: str, tool_results_text: str,
                           open_errors_text: str, interface_contracts_text: str) -> dict:
    return dict(
        role_name=role["role_name"],
        mandate=role["mandate"],
        success_metric=role["success_metric"],
        memory_scope="\n".join(f"- {k}" for k in role["memory_scope"]),
        owned_paths=format_owned_paths(role["owned_paths"]),
        reasoning=role["reasoning"],
        private_context=role.get("private_context") or "(none — you have no private information for this task)",
        roster_list=roster_list_text,
        pending_asks=pending_asks_text,
        resolved_facts=resolved_facts_text,
        stack_decisions=stack_decisions_text,
        interface_contracts=interface_contracts_text,
        role_activity=role_activity_text,
        sandbox_files=sandbox_files_text,
        normative_spec_sections=format_normative_spec_sections(task_spec.get("normative_spec_sections") or []),
        conversation=conversation,
        instruction=instruction,
        tool_results=tool_results_text,
        open_errors=open_errors_text,
    )


def build_prompt_tiers(role: dict, roster_list_text: str, resolved_facts_text: str, task_spec: dict,
                        conversation: str, instruction: str, sandbox_files_text: str,
                        stack_decisions_text: str = "(none yet — first role to name a library/approach sets it)",
                        role_activity_text: str = "(none yet — this is your first turn)",
                        pending_asks_text: str = "(none — nobody has addressed you since your last turn)",
                        tool_results_text: str = "(nothing ran since your last turn)",
                        open_errors_text: str = "(none currently open)",
                        interface_contracts_text: str = "(none published yet — nothing is callable across roles so far)",
                        ) -> tuple[str, str]:
    """(static, dynamic) -- the cache boundary. `static` is AGENT_SHELL_STATIC
    alone (identical every turn for this role/task, the cache candidate);
    `dynamic` is GROWING + EPHEMERAL, which must be sent fresh every call
    regardless of whether caching is active."""
    kwargs = _prompt_format_kwargs(
        role, roster_list_text, resolved_facts_text, task_spec, conversation, instruction,
        sandbox_files_text, stack_decisions_text, role_activity_text, pending_asks_text,
        tool_results_text, open_errors_text, interface_contracts_text,
    )
    static = AGENT_SHELL_STATIC.format(**kwargs)
    dynamic = AGENT_SHELL_GROWING.format(**kwargs) + AGENT_SHELL_EPHEMERAL.format(**kwargs)
    return static, dynamic
