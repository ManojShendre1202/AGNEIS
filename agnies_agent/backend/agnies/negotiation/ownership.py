"""Deterministic verification checking + code-enforced file ownership.

No LLM calls except ensure_verification_owners (a one-time-per-task backfill).
"""

import os
import re
import subprocess
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from backend.agnies.schemas import _coerce_json_string_field
from backend.core.services.roster_entry_service import RosterEntryService
from backend.core.services.task_spec_service import TaskSpecService

from .agent_shell import invoke_structured
from .config import VERIFICATION_OWNERS_PROMPT
from .executor import _venv_shell_env, task_sandbox_dir


def check_verification(task_spec_id: int, verification_steps: list[dict]) -> list[dict]:
    sandbox_dir = task_sandbox_dir(task_spec_id)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    unmet = []
    for step in verification_steps:
        kind = step.get("kind")
        if kind == "file_exists":
            if not (sandbox_dir / step["path"]).exists():
                unmet.append(step)
        elif kind == "file_matches":
            target = sandbox_dir / step["path"]
            if not target.exists():
                unmet.append(step)
                continue
            content = target.read_text(encoding="utf-8", errors="replace")
            if not re.search(step["pattern"], content):
                unmet.append(step)
        elif kind == "shell_command":
            try:
                result = subprocess.run(
                    step["command"], shell=True, cwd=sandbox_dir, env=_venv_shell_env(sandbox_dir),
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=60,
                )
                if result.returncode != step.get("expected_exit_code", 0):
                    unmet.append(step)
            except subprocess.TimeoutExpired:
                unmet.append(step)
    return unmet


def owning_roles_for_path(full_roster: list[dict], path_str: str) -> list[str]:
    owners = []
    for r in full_roster:
        for owned in r["owned_paths"]:
            owned_norm = owned.rstrip("/")
            if path_str == owned_norm or path_str.startswith(owned_norm + "/"):
                owners.append(r["role_name"])
                break
    return owners


def load_full_roster(task_spec_id: int) -> list[dict]:
    return [
        {
            "role_name": r["role_name"], "mandate": r["mandate"],
            "owned_paths": r["owned_paths"], "private_paths": r["private_paths"],
        }
        for r in RosterEntryService.list_for_task(task_spec_id)
    ]


def check_and_claim_ownership(task_spec_id: int, role_name: str, relative_path: str,
                               full_roster: list[dict],
                               protected_paths: list[str]) -> tuple[bool, Optional[str]]:
    """Enforces file ownership for write_file/edit_file. Rejects pre-existing
    protected paths and paths owned by another role; otherwise allows and
    auto-claims the path for the calling role if unclaimed."""
    if relative_path in protected_paths:
        return False, (
            f"{relative_path!r} already existed in the sandbox before this run "
            f"started (an externally-supplied input) — it is permanently "
            f"protected and cannot be written or overwritten by any role."
        )

    for r in full_roster:
        if r["role_name"] == role_name:
            continue
        if owning_roles_for_path([r], relative_path):
            return False, (
                f"{relative_path!r} is already owned by {r['role_name']}, not "
                f"{role_name} — coordinate with them instead of writing to it directly."
            )

    if not owning_roles_for_path([r for r in full_roster if r["role_name"] == role_name], relative_path):
        RosterEntryService.claim_path(task_spec_id, role_name, relative_path)

    return True, None


def check_read_allowed(role_name: str, relative_path: str,
                        full_roster: list[dict]) -> tuple[bool, Optional[str]]:
    """Enforces read-exclusivity for read_file. list_dir is deliberately NOT
    gated by this -- a private path's existence stays visible in a listing,
    only its content is off-limits to every role except the one it's
    private to."""
    for r in full_roster:
        if r["role_name"] == role_name:
            continue
        for private in r.get("private_paths", []):
            private_norm = private.rstrip("/")
            if relative_path == private_norm or relative_path.startswith(private_norm + "/"):
                return False, (
                    f"{relative_path!r} is private to {r['role_name']} — you may not read it."
                )
    return True, None


# ============================================================
# Backfill verification-step ownership (shell_command steps have no `path`,
# so owning_roles_for_path can't resolve them — this assigns owner_role once
# per task and persists it into task_specs.extracted_json)
# ============================================================

class VerificationOwnerAssignment(BaseModel):
    step_index: int = Field(description="Index into the TaskSpec.verification list.")
    owner_role: str = Field(description="Role name from CURRENT TEAM responsible for this check.")


class VerificationOwnersDecision(BaseModel):
    assignments: list[VerificationOwnerAssignment]

    @model_validator(mode="before")
    @classmethod
    def _coerce_assignments(cls, data):
        return _coerce_json_string_field(data, "assignments")

def ensure_verification_owners(task_spec_id: int, task_spec: dict,
                                full_roster: list[dict], api_key: str) -> tuple[dict, dict]:
    verification = task_spec.get("verification", [])
    missing = [(i, step) for i, step in enumerate(verification) if not step.get("owner_role")]
    zero_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not missing:
        return task_spec, zero_usage

    roster_text = "\n".join(f"- {r['role_name']}: {r['mandate']}" for r in full_roster)
    missing_text = "\n".join(f"{i}: {step}" for i, step in missing)
    decision, usage = invoke_structured(
        os.environ["PRIME_MODEL"],
        VerificationOwnersDecision,
        VERIFICATION_OWNERS_PROMPT.format(roster_text=roster_text, missing_text=missing_text),
        label="ensure_verification_owners LLM call",
    )

    known_roles = {r["role_name"] for r in full_roster}
    for assignment in decision.assignments:
        if assignment.owner_role not in known_roles:
            continue
        if 0 <= assignment.step_index < len(verification):
            verification[assignment.step_index]["owner_role"] = assignment.owner_role

    task_spec["verification"] = verification
    TaskSpecService.update_extracted_json_only(task_spec_id, task_spec)
    print(f"Backfilled owner_role for {len(decision.assignments)} verification step(s).")
    return task_spec, usage
