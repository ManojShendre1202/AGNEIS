"""Service wrapper over the RoleActivity model -- each role's own log of
files written, packages installed, commands run, on past turns (see
backend/agnies/negotiation/agent_shell.py)."""

from backend.core.models import RoleActivity


class RoleActivityService:
    @staticmethod
    def create(task_spec_id: int, role_name: str, action_type: str,
               detail: str, turn: int | None = None) -> RoleActivity:
        return RoleActivity.objects.create(
            task_spec_id=task_spec_id, role_name=role_name, action_type=action_type,
            detail=detail, turn=turn,
        )

    @staticmethod
    def list_for_task_and_role(task_spec_id: int, role_name: str) -> list[dict]:
        rows = RoleActivity.objects.filter(
            task_spec_id=task_spec_id, role_name=role_name
        ).order_by("id")
        return [{"action_type": r.action_type, "detail": r.detail, "turn": r.turn} for r in rows]

    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        RoleActivity.objects.filter(task_spec_id=task_spec_id).delete()
