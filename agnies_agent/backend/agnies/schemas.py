"""Pydantic schema for the structured task spec extracted from a raw task-brief md file.

See PLAN.md §8 — this is the one-time LLM extraction target. Once extracted and
verified, downstream constraint validation reads this structured form only,
never the raw prose.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field, model_validator


def _coerce_json_string_field(data, field_name: str):
    """Occasionally a model double-encodes a nested array field -- returns it
    as a JSON string (sometimes even re-wrapped in an object keyed by the
    same field name) instead of a real array. Coerce that back into a plain
    list before pydantic validates it, so a formatting quirk doesn't fail the
    whole call and cost a full retry (resend input + regenerate output) for
    data that was actually present and just needed one json.loads."""
    if not isinstance(data, dict):
        return data
    value = data.get(field_name)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return data
        if isinstance(value, dict) and field_name in value:
            value = value[field_name]
        data = {**data, field_name: value}
    return data


def _coerce_json_string_fields(data, *field_names: str):
    """Same as _coerce_json_string_field, applied to several fields at once
    -- for schemas with more than one list field prone to the same
    double-encoding quirk."""
    for field_name in field_names:
        data = _coerce_json_string_field(data, field_name)
    return data


class Constraint(BaseModel):
    name: str
    description: str
    kind: Literal["hard", "soft"] = "hard"


class Intervention(BaseModel):
    category: str
    name: str


class DynamicEvent(BaseModel):
    id: str
    name: str
    description: str
    impact: list[str]


class Metric(BaseModel):
    name: str
    objective: Literal["increase", "reduce", "maintain", "stay_within"]


class NormativeSpecSection(BaseModel):
    """A section of the source text that defines an exact format/syntax/
    contract that generated work must conform to precisely — a language
    grammar, an API schema, a file format, a protocol, a config format,
    whatever the domain calls for. `content` is copied VERBATIM from the
    source text, never paraphrased or summarized: the entire point of this
    field is that exact tokens (keywords, punctuation, field names) survive
    extraction intact, since a summary would silently lose the very details
    that make it a contract instead of a description. Not every task has
    one of these — empty is the normal case for a task with no literal
    format/syntax to conform to."""

    title: str = Field(description="The section's own heading/name in the source text.")
    content: str = Field(
        description="The section's content, copied verbatim character-for-character "
        "from the source text — do not paraphrase, summarize, or reformat it."
    )


class TaskSpec(BaseModel):
    title: str
    objective: str
    constraints: list[Constraint]
    interventions: list[Intervention]
    dynamic_events: list[DynamicEvent]
    metrics: list[Metric]
    success_criteria: list[str]
    normative_spec_sections: list[NormativeSpecSection] = Field(
        default_factory=list,
        description="Extracted separately, in its own dedicated pass below — "
        "still populate it here as best you can, but it will be reconciled "
        "afterward, so it is NOT a problem if this pass misses some of it.",
    )
    verification: list["VerificationStep"] = Field(
        default_factory=list,
        description="Structured, automatable pass/fail checks for this task "
        "(e.g. run a shell command and check its exit code, check a file "
        "exists, check a file's contents match a pattern). Replaces narrated "
        "self-reported success with a deterministic check (SANDBOX_AGENT_PLAN.md §3.4).",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_verification(cls, data):
        return _coerce_json_string_field(data, "verification")

    @model_validator(mode="before")
    @classmethod
    def _coerce_normative_spec_sections(cls, data):
        return _coerce_json_string_field(data, "normative_spec_sections")


class NormativeSpecExtraction(BaseModel):
    """Focused re-extraction target for backfilling TaskSpec.normative_spec_sections,
    same dedicated-call pattern as VerificationExtraction below (see
    extract_task_spec.py) — a big, many-field schema call is prone to dropping
    or paraphrasing a nested field like this one, and paraphrasing here is
    worse than dropping it, since it looks present while silently no longer
    being verbatim."""

    normative_spec_sections: list[NormativeSpecSection] = Field(
        default_factory=list,
        description="Every section of the source text that defines an exact "
        "format/syntax/contract generated work must conform to precisely, "
        "copied verbatim. Empty only if the text truly describes no such section.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_normative_spec_sections(cls, data):
        return _coerce_json_string_field(data, "normative_spec_sections")


class VerificationExtraction(BaseModel):
    """Focused re-extraction target for backfilling TaskSpec.verification when
    the main extraction call missed it entirely (see extract_task_spec.py) --
    TaskSpec's full schema is large enough that a lite model can silently drop
    this one nested array field; asking for just this field, alone, is far
    less likely to be skipped."""

    verification: list["VerificationStep"] = Field(
        default_factory=list,
        description="Every concrete, automatable pass/fail check stated in the "
        "source text (e.g. run a shell command and check its exit code, check a "
        "file exists, check a file's contents match a pattern). Empty only if "
        "the text truly describes no such check.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_verification(cls, data):
        return _coerce_json_string_field(data, "verification")


class VerificationStep(BaseModel):
    kind: Literal["shell_command", "file_exists", "file_matches", "llm_review"]
    command: str | None = Field(
        default=None, description="Required for kind='shell_command'."
    )
    expected_exit_code: int = Field(
        default=0, description="Used for kind='shell_command'."
    )
    path: str | None = Field(
        default=None,
        description="Sandbox-relative file path. Required for kind='file_exists' "
        "and kind='file_matches'.",
    )
    pattern: str | None = Field(
        default=None, description="Regex. Required for kind='file_matches'."
    )
    criterion: str | None = Field(
        default=None,
        description="Required for kind='llm_review'. The specific correctness/"
        "content requirement being judged, quoted close to the source text's own "
        "wording — e.g. 'produces output matching the spec', 'covers these cases', "
        "'is a genuine resolved fact, not fabricated'. Use this kind whenever a "
        "check is about whether content is CORRECT, not merely whether a process "
        "survived — a shell_command exit code or a file existing only proves the "
        "process ran / the file is there, never that what it produced is right.",
    )
    review_targets: list[str] | None = Field(
        default=None,
        description="Required for kind='llm_review'. Sandbox-relative file/directory "
        "paths and/or 'shell_command:<command>' entries whose REAL captured content "
        "the reviewer must read before judging — never a criterion with no way to "
        "fetch real evidence.",
    )
    owner_role: str | None = Field(
        default=None,
        description="Which roster role is responsible for satisfying this check. "
        "Not set at extraction time (no roster exists yet) — Prime backfills this "
        "once the roster is bootstrapped. Needed because 'shell_command'/'llm_review' "
        "steps have no path to infer ownership from the way file_exists/file_matches "
        "steps do.",
    )


# --- Prime bootstrap (Stage 2) ---------------------------------------------
# budget_calls and model_tier are deliberately NOT fields here — Prime never
# sets its own spending limit, and model_tier is always the single ROLE_MODEL
# value for every role (never a free choice), so asking the model to repeat
# a fixed string back is pure output-token waste. Our code assigns both
# after Prime proposes the roster (see prime_bootstrap.py's run_roster).

class RosterEntry(BaseModel):
    role_name: str
    mandate: str
    success_metric: str
    memory_scope: list[str] = Field(
        description="Specific state keys this role reads/writes — never 'everything'."
    )
    owned_paths: list[str] = Field(
        default_factory=list,
        description="Sandbox-relative file/directory paths this role may write to. "
        "Empty for roles that don't touch the filesystem (e.g. pure coordination "
        "roles). Other roles may read these paths but must not write to them "
        "without renegotiating ownership (SANDBOX_AGENT_PLAN.md §3.3).",
    )
    reasoning: str = Field(
        description="Why this specific role is needed for this specific project."
    )
    private_context: str = Field(
        default="",
        description="Information ONLY this role knows -- never shown to any other "
        "role's prompt (unlike mandate/reasoning, which the whole roster sees). "
        "Leave empty for ordinary tasks. Populate only when the task spec itself "
        "describes a genuine information asymmetry (e.g. a private cost/valuation "
        "one party has and another must not simply be told) that this role must "
        "hold privately and reveal only strategically, per the task's own rules "
        "for how/whether to disclose it -- never invent a private fact the task "
        "spec doesn't itself describe.",
    )
    private_paths: list[str] = Field(
        default_factory=list,
        description="Sandbox-relative file/directory paths ONLY this role may "
        "read_file -- unlike owned_paths (write-exclusive, read-open to everyone), "
        "these are read-exclusive: another role's read_file on one of these paths "
        "is rejected (though list_dir still shows the path exists -- only its "
        "content is gated). Leave empty for ordinary tasks. Populate only when the "
        "task spec itself describes a document/reference only one specific role "
        "should have direct access to (e.g. an internal policy rulebook another "
        "role must learn the boundaries of only through that role's decisions, "
        "never by reading the source itself) -- never invent a restriction the "
        "task spec doesn't itself call for.",
    )


class ResourcePool(BaseModel):
    name: str
    unit: str
    initial_count: float
    owner_role: str = Field(description="Must match a role_name in the roster.")
    reasoning: str


class PrimeBootstrap(BaseModel):
    overall_reasoning: str = Field(
        description="Prime's top-level strategy for this project: the hardest "
        "expected tradeoff and why this roster shape addresses it."
    )
    roster: list[RosterEntry]
    resource_pools: list[ResourcePool]

    @model_validator(mode="before")
    @classmethod
    def _coerce_lists(cls, data):
        return _coerce_json_string_fields(data, "roster", "resource_pools")


# --- Negotiation (Stage 3) ---------------------------------------------
# One role's turn, returned directly as structured output from the model
# (negotiation/roles.py::run_role) instead of being regex-parsed out of a
# free-text reply with hand-formatted "TOOL_USE: ..." tag lines.

class RoleToolCall(BaseModel):
    tool: Literal["read_file", "list_dir", "write_file", "edit_file", "run_shell", "install_package"]
    why: str = Field(
        description="For write_file/edit_file: the full spec of what the file "
        "must contain (fields/functions/classes/behavior), including the exact "
        "library/approach to use — stay consistent with whatever approach this "
        "project already committed to. For run_shell: why this command is "
        "needed. For install_package: why these packages are needed. For "
        "read_file/list_dir: why you need to see this content."
    )
    path: str | None = Field(
        default=None,
        description="Sandbox-relative path. Required for write_file/edit_file/"
        "read_file. Optional for list_dir (omit or '.' lists the sandbox root), "
        "otherwise omit.",
    )
    command: str | None = Field(
        default=None, description="Shell command to run. Required for run_shell, otherwise omit."
    )
    packages: list[str] | None = Field(
        default=None,
        description="Package names to install. Required for install_package, otherwise omit.",
    )


class RoleAddressedTo(BaseModel):
    role: str = Field(description="Must be a role_name that appears in CURRENT TEAM.")
    ask: str = Field(description="What you need from them.")


class RoleRequestToPrime(BaseModel):
    what: str = Field(
        description="Prefix with 'FACT:' for a genuine real-world data point that "
        "needs a grounded search, or 'GAP:' for a roster/dispatch ambiguity no "
        "existing role covers. Only use this when no role in CURRENT TEAM "
        "(including you) can supply it — a teammate question belongs in "
        "addressed_to instead."
    )
    why: str


class RoleStackDecision(BaseModel):
    package: str
    reasoning: str = Field(description="Why you're choosing this package/approach.")


class RoleInterfaceContract(BaseModel):
    path: str = Field(description="Sandbox-relative path of the file this function lives/will live in.")
    function_name: str
    signature: str = Field(
        description="The exact call shape, e.g. 'save_message(room_id: str, sender: str, "
        "payload: str) -> None' -- precise enough that a teammate can call it correctly "
        "without reading the implementation."
    )
    description: str = Field(description="One line: what it does.")


class RoleTurn(BaseModel):
    # Defaulted, not required: the model occasionally folds its narrative into
    # the last tool_call's `why` instead of top-level `response`, omitting
    # this field entirely -- failing validation over that costs a full retry
    # (resend input + regenerate output) for a field whose absence is cosmetic.
    response: str = Field(
        default="",
        description="Your narrative response/explanation for this turn — the "
        "part a teammate would actually read.",
    )
    history_note: str = Field(
        default="",
        description="ONE OR TWO SENTENCES summarizing this turn's outcome for the "
        "permanent shared conversation log every future turn (yours and "
        "teammates') will see — NOT the full `response`, which is only shown once. "
        "State the concrete decision/action/ask, not your reasoning for it (e.g. "
        "'Decided to use SQLite with WAL mode; wrote schema.py.' or 'Asked "
        "BackendRole to confirm the API port before proceeding.'), so someone "
        "skimming many turns later still gets what actually happened. Leave empty "
        "only if this turn produced nothing worth remembering later.",
    )
    tool_calls: list[RoleToolCall] = Field(
        default_factory=list,
        description="Every read_file/write_file/edit_file/run_shell/install_package "
        "action you are taking this turn. Empty if you're taking no tool action.",
    )
    addressed_to: list[RoleAddressedTo] = Field(
        default_factory=list,
        description="Teammates (from CURRENT TEAM) you are directing a question or "
        "ask to this turn, beyond what's in your response text.",
    )
    requests_to_prime: list[RoleRequestToPrime] = Field(
        default_factory=list,
        description="Escalations to Prime — only for a genuine roster gap or an "
        "unresolvable factual question. Leave empty otherwise.",
    )
    stack_decisions: list[RoleStackDecision] = Field(
        default_factory=list,
        description="Library/approach choices you are naming for the first time "
        "in this project. Leave empty if you're only using decisions already "
        "listed under PROJECT STACK DECISIONS SO FAR.",
    )
    publishes_interfaces: list[RoleInterfaceContract] = Field(
        default_factory=list,
        description="Function(s) you are making callable by other roles for the "
        "first time this turn -- publish here BEFORE or IN THE SAME TURN you "
        "write_file/edit_file the code that defines them, so a teammate never has "
        "to guess your signature. Leave empty if you're not introducing a new "
        "cross-role callable this turn.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_lists(cls, data):
        return _coerce_json_string_fields(
            data, "tool_calls", "addressed_to", "requests_to_prime",
            "stack_decisions", "publishes_interfaces",
        )
