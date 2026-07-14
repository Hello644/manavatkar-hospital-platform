from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import AiInteraction


@admin.register(AiInteraction)
class AiInteractionAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("task", "model", "created_by", "created_at")
    list_filter = ("task", "model")
    readonly_fields = ("created_at",)
