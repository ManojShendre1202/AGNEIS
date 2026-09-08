"""Service wrapper over the RosterEntry model."""

from backend.core.models import RosterEntry


class RosterEntryService:
    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        RosterEntry.objects.filter(task_spec_id=task_spec_id).delete()

    @staticmethod
    def bulk_create(task_spec_id: int, entries: list[dict]) -> list[RosterEntry]:
        objs = [
            RosterEntry(
                task_spec_id=task_spec_id,
                role_name=e["role_name"],
                mandate=e["mandate"],
                success_metric=e["success_metric"],
                model_tier=e["model_tier"],
                budget_calls=e["budget_calls"],
                memory_scope=e["memory_scope"],
                owned_paths=e.get("owned_paths", []),
                reasoning=e["reasoning"],
                private_context=e.get("private_context", ""),
                private_paths=e.get("private_paths", []),
            )
            for e in entries
        ]
        return RosterEntry.objects.bulk_create(objs)

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        rows = RosterEntry.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [
            {
                "role_name": r.role_name,
                "mandate": r.mandate,
                "success_metric": r.success_metric,
                "model_tier": r.model_tier,
                "budget_calls": r.budget_calls,
                "memory_scope": r.memory_scope,
                "owned_paths": r.owned_paths,
                "status": r.status,
                "reasoning": r.reasoning,
                "private_paths": r.private_paths,
            }
            for r in rows
        ]

    @staticmethod
    def get_role(task_spec_id: int, role_name: str) -> dict:
        try:
            r = RosterEntry.objects.get(task_spec_id=task_spec_id, role_name=role_name)
        except RosterEntry.DoesNotExist:
            raise ValueError(f"No roster row for task_spec_id={task_spec_id}, role_name={role_name!r}")
        return {
            "role_name": r.role_name,
            "mandate": r.mandate,
            "success_metric": r.success_metric,
            "model_tier": r.model_tier,
            "memory_scope": r.memory_scope,
            "owned_paths": r.owned_paths,
            "reasoning": r.reasoning,
            "private_context": r.private_context,
        }

    @staticmethod
    def claim_path(task_spec_id: int, role_name: str, relative_path: str) -> None:
        r = RosterEntry.objects.get(task_spec_id=task_spec_id, role_name=role_name)
        if relative_path not in r.owned_paths:
            r.owned_paths = [*r.owned_paths, relative_path]
            r.save(update_fields=["owned_paths"])
