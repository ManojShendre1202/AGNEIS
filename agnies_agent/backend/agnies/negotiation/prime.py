"""Prime resolving REQUEST_TO_PRIME — split into a routing decision (no
search tool bound) and a real grounded-search fact lookup, never guessed."""

import json
import os
from typing import Optional

from pydantic import BaseModel, Field

from .agent_shell import extract_usage, invoke_structured
from .config import GROUNDED_SEARCH_PROMPT, PRIME_ROUTING_PROMPT
from .llm_factory import build_chat_model
from .rate_limit import GEMINI_RATE_LIMITER, estimate_tokens
from .retry import call_with_retry

_ROUTING_CONVERSATION_TAIL_CHARS = 6000


class PrimeRoutingDecision(BaseModel):
    next_role: Optional[str] = Field(
        description="Role name (must be one of CURRENT TEAM) that should act "
        "next, or null if there is no clear next actor."
    )
    reasoning: str

def prime_resolve_routing(api_key: str, task_spec: dict, full_roster: list[dict],
                           pending: dict, conversation: str) -> tuple[PrimeRoutingDecision, dict]:
    roster_text = "\n".join(f"- {r['role_name']}: {r['mandate']}" for r in full_roster)
    if len(conversation) > _ROUTING_CONVERSATION_TAIL_CHARS:
        recent_conversation = (
            "... (earlier conversation truncated) ...\n"
            + conversation[-_ROUTING_CONVERSATION_TAIL_CHARS:]
        )
    else:
        recent_conversation = conversation or "(no conversation yet)"
    prompt = PRIME_ROUTING_PROMPT.format(
        roster_text=roster_text,
        from_role=pending["from_role"],
        what=pending["what"],
        why=pending["why"],
        recent_conversation=recent_conversation,
        task_spec_json=json.dumps(task_spec, indent=2),
    )
    return invoke_structured(os.environ["PRIME_MODEL"], PrimeRoutingDecision, prompt,
                              label="prime_resolve_routing LLM call")


def prime_resolve_fact(api_key: str, topic: str, why: str) -> tuple[str, list[str], dict]:

    llm = build_chat_model(os.environ["GROUNDING_MODEL"])
    search_llm = llm.bind_tools([{"google_search": {}}])
    prompt = GROUNDED_SEARCH_PROMPT.format(topic=topic, why=why)
    label = "prime_resolve_fact grounded search LLM call"
    GEMINI_RATE_LIMITER.acquire(estimate_tokens(prompt), label=label)
    response = call_with_retry(lambda: search_llm.invoke(prompt), label=label)
    GEMINI_RATE_LIMITER.record(extract_usage(response).get("total_tokens", 0))
    findings = response.content if isinstance(response.content, str) else str(response.content)
    sources: list[str] = []
    try:
        metadata = response.response_metadata.get("grounding_metadata") or {}
        for chunk in metadata.get("grounding_chunks", []):
            url = chunk.get("web", {}).get("uri")
            if url:
                sources.append(url)
    except AttributeError:
        pass
    return findings, sources, extract_usage(response)


def is_fact_request(what: str) -> bool:
    normalized = what.strip().upper()
    return normalized.startswith("FACT") or "SEARCH_NEEDED(" in normalized
