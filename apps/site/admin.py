from django.contrib import admin

from .models import Announcement, PublicBookingAttempt, Service


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["name", "name_marathi", "display_order", "is_active"]
    list_editable = ["display_order", "is_active"]
    search_fields = ["name", "name_marathi"]


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "starts_on", "ends_on", "is_active"]
    list_filter = ["is_active"]
    search_fields = ["title", "body"]


@admin.register(PublicBookingAttempt)
class PublicBookingAttemptAdmin(admin.ModelAdmin):
    """Read-only abuse trail. Rows age out via `manage.py purge_booking_attempts`;
    editing them by hand would defeat the point of having the record."""

    list_display = ["created_at", "outcome", "mobile", "ip_address", "detail"]
    list_filter = ["outcome", "created_at"]
    search_fields = ["mobile", "ip_address"]
    readonly_fields = ["created_at", "outcome", "mobile", "ip_address", "detail"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
