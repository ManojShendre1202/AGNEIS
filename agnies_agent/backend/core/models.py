"""Core AGNIES data model — Django ORM replacement for the old hand-written
schema.sql / raw sqlite3.connect() access pattern (see backend/db/legacy_schema.sql
and backend/db/legacy_agnies.db for the previous version, kept for reference only,
not migrated).

Table shape mirrors the legacy schema 1:1 (task_specs, research_notes, roster,
resource_pools, resolved_facts, stack_decisions, role_activity) so existing
pipeline logic in backend/agnies/* maps onto this cleanly once it's rewired to
go through services instead of sqlite3 directly. JSON TEXT columns become
JSONField; free-standing 'task_spec_id INTEGER' FKs become real ForeignKeys.
"""

from django.db import models


class TaskSpec(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),           # uploaded, extraction not run yet
        ("extracted", "Extracted"),       # LLM extraction done, awaiting human verify
        ("verified", "Verified"),         # human confirmed, ready for roster stage
        ("roster_created", "Roster created"),  # Prime bootstrap done (stage 2 complete)
        ("negotiating", "Negotiating"),   # stage 3 run in progress
        ("done", "Done"),                 # stage 3 verification passed / Prime ended it
    ]
    NEGOTIATION_MODE_CHOICES = [
        ("dev", "Dev (step-by-step)"),
        ("prod", "Prod (continuous)"),
    ]

    source_filename = models.CharField(max_length=255)
    raw_text = models.TextField()
    extracted_json = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    prime_overall_reasoning = models.TextField(null=True, blank=True)
    negotiation_mode = models.CharField(
        max_length=10, choices=NEGOTIATION_MODE_CHOICES, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "task_specs"

    def __str__(self) -> str:
        return f"{self.source_filename} ({self.status})"


class ResearchNote(models.Model):
    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="research_notes")
    topic = models.CharField(max_length=255)
    findings = models.TextField()
    sources = models.JSONField(null=True, blank=True, default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "research_notes"

    def __str__(self) -> str:
        return f"{self.topic} (task_spec={self.task_spec_id})"


class RosterEntry(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("retired", "Retired"),
    ]

    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="roster")
    role_name = models.CharField(max_length=255)
    mandate = models.TextField()
    success_metric = models.TextField()
    model_tier = models.CharField(max_length=100)
    budget_calls = models.IntegerField()
    memory_scope = models.JSONField(default=list)
    owned_paths = models.JSONField(default=list)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    reasoning = models.TextField()
    # Known only to this role -- deliberately never surfaced via list_for_task
    # (the shared roster view every role's prompt sees), only via get_role
    # (this role's own prompt). See schemas.RosterEntry.private_context.
    private_context = models.TextField(blank=True, default="")
    # Read-exclusive paths (unlike owned_paths, which is write-exclusive but
    # read-open) -- DOES need to be visible via list_for_task, unlike
    # private_context, since every OTHER role's read_file check needs to see
    # the whole roster's private_paths to know what's off-limits to them.
    # See schemas.RosterEntry.private_paths, ownership.check_read_allowed.
    private_paths = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "roster"

    def __str__(self) -> str:
        return f"{self.role_name} (task_spec={self.task_spec_id})"


class ResourcePool(models.Model):
    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="resource_pools")
    name = models.CharField(max_length=255)
    unit = models.CharField(max_length=100)
    initial_count = models.FloatField()
    # Kept as a plain string matching roster.role_name, same convention as the
    # legacy schema (not a real FK there either) — a resource pool is owned by
    # one role but roster role_name isn't a unique/primary key to FK against.
    owner_role = models.CharField(max_length=255)
    reasoning = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "resource_pools"

    def __str__(self) -> str:
        return f"{self.name} (task_spec={self.task_spec_id})"


class ResolvedFact(models.Model):
    STATUS_CHOICES = [
        ("resolved", "Resolved"),
        ("unresolved", "Unresolved"),
    ]

    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="resolved_facts")
    topic = models.CharField(max_length=255)
    value = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    source = models.CharField(max_length=500, null=True, blank=True)
    resolved_by_role = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "resolved_facts"

    def __str__(self) -> str:
        return f"{self.topic} (task_spec={self.task_spec_id})"


class StackDecision(models.Model):
    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="stack_decisions")
    package = models.CharField(max_length=255)
    version = models.CharField(max_length=100, null=True, blank=True)
    decided_by_role = models.CharField(max_length=255)
    reasoning = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stack_decisions"

    def __str__(self) -> str:
        return f"{self.package} (task_spec={self.task_spec_id})"


class InterfaceContract(models.Model):
    """A published function/interface one role owns, so a teammate can check
    it exists (and its exact signature) before writing code that calls it,
    instead of guessing a name/shape and finding out it's wrong several
    turns later when integration breaks (see agent_shell.py/roles.py)."""

    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="interface_contracts")
    owner_role = models.CharField(max_length=255)
    path = models.CharField(max_length=500)
    function_name = models.CharField(max_length=255)
    signature = models.CharField(max_length=500)
    description = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "interface_contracts"

    def __str__(self) -> str:
        return f"{self.function_name} ({self.path}, task_spec={self.task_spec_id})"


class RoleActivity(models.Model):
    ACTION_CHOICES = [
        ("write_file", "Write file"),
        ("edit_file", "Edit file"),
        ("install_package", "Install package"),
        ("run_shell", "Run shell"),
        ("bug_fix", "Bug fix"),
    ]

    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="role_activity")
    role_name = models.CharField(max_length=255)
    action_type = models.CharField(max_length=30, choices=ACTION_CHOICES)
    detail = models.TextField()
    turn = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "role_activity"

    def __str__(self) -> str:
        return f"{self.role_name}: {self.action_type} (task_spec={self.task_spec_id})"


class NegotiationTurn(models.Model):
    """One node in the negotiate stage's live turn tree (negotiation/graph.py).
    A node holds every entry the same role produced back-to-back -- an
    initial turn plus any reflect/fact-resolution continuation immediately
    after it -- rather than one row per LLM call (see graph.py's merge rule:
    same role, dispatched immediately again -> same node)."""

    task_spec = models.ForeignKey(TaskSpec, on_delete=models.CASCADE, related_name="negotiation_turns")
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="children"
    )
    role_name = models.CharField(max_length=255)
    model_tier = models.CharField(max_length=100)
    first_turn = models.IntegerField()
    entries = models.JSONField(default=list)
    tool_results = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "negotiation_turns"

    def __str__(self) -> str:
        return f"{self.role_name} (task_spec={self.task_spec_id}, turn={self.first_turn})"
