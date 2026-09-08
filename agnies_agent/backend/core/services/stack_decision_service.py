"""Service wrapper over the StackDecision model -- the shared, checked-first
record of library/approach choices every role commits to (see
backend/agnies/negotiation/agent_shell.py)."""

from backend.core.models import StackDecision


class StackDecisionService:
    @staticmethod
    def create(task_spec_id: int, package: str, version: str | None,
               decided_by_role: str, reasoning: str) -> StackDecision:
        return StackDecision.objects.create(
            task_spec_id=task_spec_id, package=package, version=version,
            decided_by_role=decided_by_role, reasoning=reasoning,
        )

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        rows = StackDecision.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [
            {
                "package": r.package,
                "version": r.version,
                "decided_by_role": r.decided_by_role,
                "reasoning": r.reasoning,
            }
            for r in rows
        ]

    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        StackDecision.objects.filter(task_spec_id=task_spec_id).delete()
