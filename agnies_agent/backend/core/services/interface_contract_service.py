"""Service wrapper over the InterfaceContract model -- the shared, checked-
first registry of function signatures a role has published for others to
call (see backend/agnies/negotiation/agent_shell.py)."""

from backend.core.models import InterfaceContract


class InterfaceContractService:
    @staticmethod
    def create(task_spec_id: int, owner_role: str, path: str, function_name: str,
               signature: str, description: str) -> InterfaceContract:
        return InterfaceContract.objects.create(
            task_spec_id=task_spec_id, owner_role=owner_role, path=path,
            function_name=function_name, signature=signature, description=description,
        )

    @staticmethod
    def upsert(task_spec_id: int, owner_role: str, path: str, function_name: str,
               signature: str, description: str) -> tuple[InterfaceContract, bool]:
        """Republishing an already-known function_name UPDATES its record in
        place instead of being silently dropped -- a stale signature that no
        longer matches the real implementation is worse than no record at
        all (see PLAN discussion: a role that changes a function's shape
        must be able to correct the published contract, not just add a
        second, ignored entry)."""
        return InterfaceContract.objects.update_or_create(
            task_spec_id=task_spec_id, function_name=function_name,
            defaults={"owner_role": owner_role, "path": path,
                      "signature": signature, "description": description},
        )

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        rows = InterfaceContract.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [
            {
                "owner_role": r.owner_role,
                "path": r.path,
                "function_name": r.function_name,
                "signature": r.signature,
                "description": r.description,
            }
            for r in rows
        ]

    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        InterfaceContract.objects.filter(task_spec_id=task_spec_id).delete()
