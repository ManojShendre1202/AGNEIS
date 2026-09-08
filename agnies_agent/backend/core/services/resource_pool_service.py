"""Service wrapper over the ResourcePool model."""

from backend.core.models import ResourcePool


class ResourcePoolService:
    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        ResourcePool.objects.filter(task_spec_id=task_spec_id).delete()

    @staticmethod
    def bulk_create(task_spec_id: int, pools: list[dict]) -> list[ResourcePool]:
        objs = [
            ResourcePool(
                task_spec_id=task_spec_id,
                name=p["name"],
                unit=p["unit"],
                initial_count=p["initial_count"],
                owner_role=p["owner_role"],
                reasoning=p["reasoning"],
            )
            for p in pools
        ]
        return ResourcePool.objects.bulk_create(objs)

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        rows = ResourcePool.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [
            {
                "name": r.name,
                "unit": r.unit,
                "initial_count": r.initial_count,
                "owner_role": r.owner_role,
                "reasoning": r.reasoning,
            }
            for r in rows
        ]
