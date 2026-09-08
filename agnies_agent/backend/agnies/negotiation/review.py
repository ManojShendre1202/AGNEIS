import os
from pathlib import Path

from pydantic import BaseModel, Field, model_validator

from backend.agnies.schemas import _coerce_json_string_field

from .agent_shell import invoke_structured
from .config import CLOSE_REVIEW_PROMPT
from .executor import (
    _excluded_path_reason,
    _SANDBOX_LISTING_EXCLUDED_DIRS,
    execute_run_shell,
    task_sandbox_dir,
)


class ReviewFinding(BaseModel):
    criterion: str
    passed: bool
    evidence: str = Field(description="The actual content/output that grounds this verdict.")


class ReviewVerdict(BaseModel):
    findings: list[ReviewFinding]
    all_passed: bool

    @model_validator(mode="before")
    @classmethod
    def _coerce_findings(cls, data):
        return _coerce_json_string_field(data, "findings")

_BINARY_SKIP_EXTENSIONS = {".pyc", ".pyo", ".so", ".dll", ".exe", ".db", ".sqlite", ".sqlite3", ".pkl", ".pyd"}

def _is_binary_artifact(path: Path) -> bool:
    return path.suffix.lower() in _BINARY_SKIP_EXTENSIONS


def _evidence_for_target(sandbox_dir: Path, task_spec_id: int, target: str) -> str:
    if target.startswith("shell_command:"):
        command = target.split(":", 1)[1].strip()
        result = execute_run_shell(task_spec_id, command)
        body = (
            f"exit code: {result.get('returncode')}\n"
            f"stdout:\n{result.get('stdout') or '(empty)'}\n"
            f"stderr:\n{result.get('stderr') or result.get('error') or '(empty)'}"
        )
        return f"--- shell_command: {command} ---\n{body}"

    sandbox_dir = sandbox_dir.resolve()
    path = (sandbox_dir / target).resolve()
    excluded_reason = _excluded_path_reason(task_spec_id, path)
    if excluded_reason:
        return f"--- {target} --- (SKIPPED — {excluded_reason})"
    if path.is_dir():
        sections = [
            f"--- {f.relative_to(sandbox_dir).as_posix()} ---\n"
            f"{f.read_text(encoding='utf-8', errors='replace')}"
            for f in sorted(p for p in path.rglob("*") if p.is_file() and not _is_binary_artifact(p)
                             and not _SANDBOX_LISTING_EXCLUDED_DIRS.intersection(p.relative_to(sandbox_dir).parts))
        ]
        return "\n\n".join(sections) if sections else f"--- {target} --- (empty directory)"
    if path.exists():
        content = path.read_text(encoding="utf-8", errors="replace")
        return f"--- {target} ---\n{content}"
    return f"--- {target} --- (MISSING — does not exist)"


def _gather_all_evidence(task_spec_id: int, steps: list[dict]) -> str:
    """Computes and renders each unique review_target's evidence exactly
    once, regardless of how many criteria/steps reference it -- several
    llm_review steps commonly share a target (e.g. "inventory/" or
    "shell_command:pytest -v"), and embedding a fresh copy of a whole
    directory dump or full pytest output per criterion that mentions it
    multiplied the prompt size by however many criteria shared it, for zero
    new information each time (same bug class as the extraction stage's old
    3-call redundant resend)."""
    sandbox_dir = task_sandbox_dir(task_spec_id)
    cache: dict[str, str] = {}
    order: list[str] = []
    for step in steps:
        for target in step.get("review_targets") or []:
            if target not in cache:
                cache[target] = _evidence_for_target(sandbox_dir, task_spec_id, target)
                order.append(target)
    return "\n\n".join(cache[t] for t in order) if order else "(no evidence gathered)"


def run_close_review(task_spec_id: int, task_spec: dict, api_key: str) -> tuple[ReviewVerdict, dict]:
    steps = [s for s in task_spec.get("verification", []) if s.get("kind") == "llm_review"]
    zero_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not steps:
        return ReviewVerdict(findings=[], all_passed=True), zero_usage

    evidence_text = _gather_all_evidence(task_spec_id, steps)
    criteria_blocks = [
        f"CRITERION: {step['criterion']}\n"
        f"(relevant evidence above: {', '.join(step.get('review_targets') or []) or 'none'})"
        for step in steps
    ]

    prompt = CLOSE_REVIEW_PROMPT.format(
        objective=task_spec.get("objective", ""),
        success_criteria="\n".join(f"- {c}" for c in task_spec.get("success_criteria", [])),
        evidence_text=evidence_text,
        criteria_text="\n\n".join(criteria_blocks),
    )
    verdict, usage = invoke_structured(os.environ["PRIME_MODEL"], ReviewVerdict, prompt,
                                        label="run_close_review LLM call")

    verdict.all_passed = all(f.passed for f in verdict.findings)
    return verdict, usage
