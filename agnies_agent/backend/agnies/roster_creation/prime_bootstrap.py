import json
import os

from dotenv import load_dotenv

from backend.agnies.negotiation.agent_shell import invoke_structured
from backend.agnies.schemas import PrimeBootstrap
from backend.core.services.resource_pool_service import ResourcePoolService
from backend.core.services.roster_entry_service import RosterEntryService
from backend.core.services.task_spec_service import TaskSpecService

# System-owned default — Prime never sets this itself.
DEFAULT_BUDGET_CALLS = 5

ROLE_CATALOG = [
    "Backend Developer", "Frontend Developer", "Full Stack Developer", "API Developer",
    "Data Engineer", "Data Analyst", "Data Scientist", "ETL Developer",
    "Database Administrator", "QA Engineer", "Test Automation Engineer", "DevOps Engineer",
    "Release Engineer", "Build Engineer", "Infrastructure Engineer", "Security Engineer",
    "Performance Engineer", "Monitoring Engineer", "Technical Writer", "Reporting Analyst",
    "Data Visualization Engineer", "ML Engineer", "Research Engineer", "Systems Architect",
    "Integration Engineer", "Migration Engineer", "Compliance/Validation Engineer",
    "UI/UX Designer", "Business Analyst", "Configuration Engineer",
    "Customer Support Representative", "Policy Compliance Officer",
    "Hiring Manager", "Candidate Representative",
]

BOOTSTRAP_PROMPT = """\
You are Prime, AGNIES's meta-agent. Given the verified task spec below, \
decide ONLY the roster (one role, or several) and any non-agent resource
pools this project needs — a one-time planning step, not execution.

FIRST DECISION — one role, or several? Default to ONE role for the whole
scope. Split only if a constraint/dynamic_event forces genuine
opposing-stake negotiation (someone must be able to say no to someone
else) — never just because there are multiple steps/files (see rule 5).
EXCEPTION: if the task spec explicitly names single-agent or multi-role
execution, follow that as a hard override regardless of your own read.

Rules:
1. role_name: from ROLE ARCHETYPES below only, qualify duplicates (e.g.
   "Backend Developer — Auth"); only for a role making a genuine distinct
   decision, never plain labor (a resource pool) or a ceremonial role.
   memory_scope: specific state keys, never "everything".
   owned_paths: sandbox-relative write paths, non-overlapping between
   roles; empty if a role touches no files.
   reasoning: why THIS role for THIS project, grounded in its actual
   objective/constraints/events — not generic.
   private_context: empty unless the spec itself describes a genuine
   information asymmetry one role must hold privately — if set, it's the
   ONLY place that fact may appear (never restate it in mandate/reasoning,
   which the whole roster sees). Write the ACTUAL value(s) verbatim — exact
   numbers, thresholds, names, wording — copied from wherever they appear
   in the TASK SPEC below, never a description of where to find them. There
   is no "Baseline Parameters" field or any other section for this role to
   look up later — this prompt is the only thing that role will ever see,
   so "per Baseline Parameters" / "see the spec" / "known only to you" with
   no actual figure attached is USELESS to that role and counts as leaving
   private_context empty. If a private figure only appears bundled with the
   other role's figure in one shared sentence (e.g. a success criterion
   written for a reviewer who may see both), split it yourself: copy only
   this role's own number(s) into its private_context, and only the other
   role's number(s) into that role's.
   private_paths: empty unless the spec itself describes a document only
   one role may read_file — read-exclusive to that role (unlike
   owned_paths, which stays readable by everyone). Never invent either.
2. resource_pools: plain integer capacity (workforce/equipment/materials),
   never an LLM agent; owner_role must match a roster role_name.
3. overall_reasoning: 2-4 sentences — your strategy, the hardest tradeoff
   you expect, why this roster shape addresses it.
4. Ground every decision in the task spec below — never invent objectives,
   constraints, or events beyond what's given.
5. Roster-size discipline — the smallest roster where every role does
   something no other role could:
   - No role for fact-finding/gap-escalation alone (that's already covered
     outside the roster) or generic "oversee/coordinate" with empty
     owned_paths — unless the task names one specific cross-cutting
     decision no content-owning role could make.
   - Renegotiation test before splitting two intervention categories into
     separate roles: would the downstream role ever need to address the
     upstream one to renegotiate (a constraint/event forces it), or does
     it just consume the upstream output once with no back-and-forth?
     One-directional consumption is ONE role's job — "feels like different
     work" alone isn't enough. If a constraint/event genuinely requires two
     roles to detect and renegotiate with each other, keep them separate.
   - Exception: never fold an independent verification/testing requirement
     into the role whose output it checks, even to cut headcount.

--- AVAILABLE ROLE ARCHETYPES ---
{role_catalog}
--- END AVAILABLE ROLE ARCHETYPES ---

--- TASK SPEC (verified) ---
{task_spec_json}
--- END TASK SPEC ---
"""


def run_bootstrap(task_spec: dict) -> PrimeBootstrap:
    prompt = BOOTSTRAP_PROMPT.format(
        role_catalog=", ".join(ROLE_CATALOG),
        task_spec_json=json.dumps(task_spec, indent=2),
    )
    bootstrap, usage = invoke_structured(os.environ["PRIME_MODEL"], PrimeBootstrap, prompt,
                                          label="run_bootstrap LLM call")
    print(f"    [TOKENS] run_bootstrap: input={usage['input_tokens']} output={usage['output_tokens']} "
          f"total={usage['total_tokens']}")
    return bootstrap


def run_roster(task_spec_id: int) -> dict:
    task_spec_row = TaskSpecService.get(task_spec_id)

    if task_spec_row.status not in ("verified", "roster_created"):
        raise ValueError(
            f"task_spec_id={task_spec_id} has status={task_spec_row.status!r}, "
            f"not 'verified' — call /api/tasks/{task_spec_id}/verify/ first."
        )
    task_spec = task_spec_row.extracted_json

    load_dotenv()

    role_model = os.environ["ROLE_MODEL"]

    bootstrap = run_bootstrap(task_spec)

    roster_dicts = [
        {
            "role_name": r.role_name,
            "mandate": r.mandate,
            "success_metric": r.success_metric,
            "model_tier": role_model,
            "budget_calls": DEFAULT_BUDGET_CALLS,
            "memory_scope": r.memory_scope,
            "owned_paths": r.owned_paths,
            "reasoning": r.reasoning,
            "private_context": r.private_context,
            "private_paths": r.private_paths,
        }
        for r in bootstrap.roster
    ]
    pool_dicts = [
        {
            "name": p.name,
            "unit": p.unit,
            "initial_count": p.initial_count,
            "owner_role": p.owner_role,
            "reasoning": p.reasoning,
        }
        for p in bootstrap.resource_pools
    ]

    RosterEntryService.delete_for_task(task_spec_id)
    ResourcePoolService.delete_for_task(task_spec_id)
    RosterEntryService.bulk_create(task_spec_id, roster_dicts)
    ResourcePoolService.bulk_create(task_spec_id, pool_dicts)
    TaskSpecService.mark_roster_created(task_spec_id, bootstrap.overall_reasoning)

    nodes = [{"id": "Prime", "label": "Prime"}] + [
        {"id": r["role_name"], "label": r["role_name"]} for r in roster_dicts
    ]
    edges = [{"from": "Prime", "to": r["role_name"], "label": r["model_tier"]} for r in roster_dicts]

    return {
        "nodes": nodes,
        "edges": edges,
        "roster": roster_dicts,
        "resource_pools": pool_dicts,
        "overall_reasoning": bootstrap.overall_reasoning,
    }
