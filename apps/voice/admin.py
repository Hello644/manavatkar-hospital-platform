from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import CallSession


@admin.register(CallSession)
class CallSessionAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("call_sid", "from_number", "status", "booked_appointment", "created_at")
    list_filter = ("status",)
    search_fields = ("call_sid", "from_number")
    readonly_fields = ("created_at", "ended_at", "messages")
