"""Service wrapper over the ResolvedFact model -- the shared fact-resolution
cache every role checks before re-asking/re-searching the same real-world
fact (see backend/agnies/negotiation/agent_shell.py)."""

from backend.core.models import ResolvedFact


class ResolvedFactService:
    @staticmethod
    def create(task_spec_id: int, topic: str, value: str, status: str,
               source: str, resolved_by_role: str) -> ResolvedFact:
        return ResolvedFact.objects.create(
            task_spec_id=task_spec_id, topic=topic, value=value, status=status,
            source=source, resolved_by_role=resolved_by_role,
        )

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        rows = ResolvedFact.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [
            {
                "topic": r.topic,
                "value": r.value,
                "status": r.status,
                "source": r.source,
                "resolved_by_role": r.resolved_by_role,
            }
            for r in rows
        ]

    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        ResolvedFact.objects.filter(task_spec_id=task_spec_id).delete()
