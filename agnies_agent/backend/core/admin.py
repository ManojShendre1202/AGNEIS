from django.contrib import admin

from .models import (
    NegotiationTurn,
    ResearchNote,
    ResolvedFact,
    ResourcePool,
    RoleActivity,
    RosterEntry,
    StackDecision,
    TaskSpec,
)

admin.site.register(TaskSpec)
admin.site.register(ResearchNote)
admin.site.register(RosterEntry)
admin.site.register(ResourcePool)
admin.site.register(ResolvedFact)
admin.site.register(StackDecision)
admin.site.register(RoleActivity)
admin.site.register(NegotiationTurn)
