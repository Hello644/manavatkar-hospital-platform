from django.contrib import admin

from .models import OutboundMessage


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("channel", "to_number", "purpose", "status", "patient", "created_at")
    list_filter = ("channel", "status", "purpose")
    search_fields = ("to_number", "patient__full_name", "patient__uhid")
    readonly_fields = ("created_at", "sent_at")
