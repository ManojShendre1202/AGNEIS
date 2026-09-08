"""Service wrapper over the ResearchNote model."""

from backend.core.models import ResearchNote


class ResearchNoteService:
    @staticmethod
    def create(task_spec_id: int, topic: str, findings: str, sources: list[str]) -> ResearchNote:
        return ResearchNote.objects.create(
            task_spec_id=task_spec_id, topic=topic, findings=findings, sources=sources
        )
