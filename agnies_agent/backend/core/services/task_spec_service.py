"""Service wrapper over the TaskSpec model -- the one place that owns
task_specs queries, used directly by both backend.core (views/admin) and
backend.agnies.* pipeline code, in-process, no HTTP hop.
"""

from backend.core.models import TaskSpec


class TaskSpecService:
    @staticmethod
    def create_from_upload(source_filename: str, raw_text: str) -> TaskSpec:
        return TaskSpec.objects.create(
            source_filename=source_filename,
            raw_text=raw_text,
            status="pending",
        )

    @staticmethod
    def get(task_spec_id: int) -> TaskSpec:
        return TaskSpec.objects.get(pk=task_spec_id)

    @staticmethod
    def exists(task_spec_id: int) -> bool:
        return TaskSpec.objects.filter(pk=task_spec_id).exists()

    @staticmethod
    def list_all() -> list[dict]:
        """Summary row per task for the landing table -- not the full
        get_state() payload, just enough to identify and resume a run."""
        rows = TaskSpec.objects.order_by("-created_at").values(
            "id", "source_filename", "status", "extracted_json", "created_at"
        )
        return [
            {
                "task_spec_id": r["id"],
                "source_filename": r["source_filename"],
                "status": r["status"],
                "objective": (r["extracted_json"] or {}).get("objective"),
                "created_at": r["created_at"].isoformat(),
            }
            for r in rows
        ]

    @staticmethod
    def update_extracted(task_spec_id: int, extracted_json: dict) -> TaskSpec:
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.extracted_json = extracted_json
        task_spec.status = "extracted"
        task_spec.save(update_fields=["extracted_json", "status", "updated_at"])
        return task_spec

    @staticmethod
    def update_extracted_json_only(task_spec_id: int, extracted_json: dict) -> TaskSpec:
        """Like update_extracted, but doesn't touch status -- used by the
        verification-owner backfill (ownership.py), which only patches
        extracted_json.verification[*].owner_role onto an already
        verified/roster_created task."""
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.extracted_json = extracted_json
        task_spec.save(update_fields=["extracted_json", "updated_at"])
        return task_spec

    @staticmethod
    def mark_verified(task_spec_id: int) -> TaskSpec:
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.status = "verified"
        task_spec.save(update_fields=["status", "updated_at"])
        return task_spec

    @staticmethod
    def mark_roster_created(task_spec_id: int, prime_overall_reasoning: str) -> TaskSpec:
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.status = "roster_created"
        task_spec.prime_overall_reasoning = prime_overall_reasoning
        task_spec.save(update_fields=["status", "prime_overall_reasoning", "updated_at"])
        return task_spec

    @staticmethod
    def mark_negotiating(task_spec_id: int, mode: str) -> TaskSpec:
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.status = "negotiating"
        task_spec.negotiation_mode = mode
        task_spec.save(update_fields=["status", "negotiation_mode", "updated_at"])
        return task_spec

    @staticmethod
    def mark_negotiation_done(task_spec_id: int) -> TaskSpec:
        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        task_spec.status = "done"
        task_spec.save(update_fields=["status", "updated_at"])
        return task_spec

    @staticmethod
    def delete(task_spec_id: int) -> None:
        """Deletes the task_spec row -- every related table (roster,
        negotiation_turns, resolved_facts, stack_decisions,
        interface_contracts, role_activity, resource_pools, research_notes)
        cascades via each model's own ForeignKey(on_delete=CASCADE), see
        models.py. Sandbox files on disk are separate from the DB and don't
        cascade, so clear those explicitly too."""
        from backend.agnies.negotiation.executor import clear_sandbox_dir

        clear_sandbox_dir(task_spec_id)
        TaskSpec.objects.filter(pk=task_spec_id).delete()

    @staticmethod
    def get_state(task_spec_id: int) -> dict:
        """Full current state for the frontend to resume from on reload --
        everything it needs to reconstruct the UI without replaying events."""
        from backend.core.services.negotiation_turn_service import NegotiationTurnService
        from backend.core.services.resource_pool_service import ResourcePoolService
        from backend.core.services.roster_entry_service import RosterEntryService

        task_spec = TaskSpec.objects.get(pk=task_spec_id)
        return {
            "task_spec_id": task_spec.id,
            "status": task_spec.status,
            "source_filename": task_spec.source_filename,
            "extracted_json": task_spec.extracted_json,
            "prime_overall_reasoning": task_spec.prime_overall_reasoning,
            "roster": RosterEntryService.list_for_task(task_spec_id),
            "resource_pools": ResourcePoolService.list_for_task(task_spec_id),
            "negotiation_mode": task_spec.negotiation_mode,
            "negotiation_tree": NegotiationTurnService.list_for_task(task_spec_id),
        }
