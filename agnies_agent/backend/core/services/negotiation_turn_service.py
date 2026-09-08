"""Service wrapper over NegotiationTurn -- one row per tree node in the
negotiate stage's live turn tree (negotiation/graph.py). A node accumulates
every entry the same role produces back-to-back (its initial turn plus any
reflect/fact-resolution continuation right after it) as a list, instead of
one row per LLM call.
"""

from backend.core.models import NegotiationTurn


class NegotiationTurnService:
    @staticmethod
    def create_node(task_spec_id: int, parent_id: int | None, role_name: str,
                     model_tier: str, first_turn: int, entry: dict) -> dict:
        node = NegotiationTurn.objects.create(
            task_spec_id=task_spec_id, parent_id=parent_id, role_name=role_name,
            model_tier=model_tier, first_turn=first_turn, entries=[entry],
        )
        return NegotiationTurnService._serialize(node)

    @staticmethod
    def append_entry(node_id: int, entry: dict) -> None:
        node = NegotiationTurn.objects.get(pk=node_id)
        node.entries = node.entries + [entry]
        node.save(update_fields=["entries"])

    @staticmethod
    def append_tool_results(node_id: int, results: list[dict]) -> None:
        if not results:
            return
        node = NegotiationTurn.objects.get(pk=node_id)
        node.tool_results = node.tool_results + results
        node.save(update_fields=["tool_results"])

    @staticmethod
    def list_for_task(task_spec_id: int) -> list[dict]:
        nodes = NegotiationTurn.objects.filter(task_spec_id=task_spec_id).order_by("id")
        return [NegotiationTurnService._serialize(n) for n in nodes]

    @staticmethod
    def delete_for_task(task_spec_id: int) -> None:
        NegotiationTurn.objects.filter(task_spec_id=task_spec_id).delete()

    @staticmethod
    def _serialize(node: NegotiationTurn) -> dict:
        return {
            "id": node.id,
            "parent_id": node.parent_id,
            "role_name": node.role_name,
            "model_tier": node.model_tier,
            "first_turn": node.first_turn,
            "entries": node.entries,
            "tool_results": node.tool_results,
        }
