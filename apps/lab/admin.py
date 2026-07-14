from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import LabOrder, LabOrderItem, LabTest


@admin.register(LabTest)
class LabTestAdmin(admin.ModelAdmin):
    list_display = ("name", "short_code", "category", "sample_type", "usage_count", "is_active")
    list_filter = ("category", "sample_type", "is_active")
    search_fields = ("name", "short_code")


class LabOrderItemInline(admin.TabularInline):
    model = LabOrderItem
    extra = 0


@admin.register(LabOrder)
class LabOrderAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    inlines = [LabOrderItemInline]
    list_display = ("short_id", "patient", "doctor", "status", "created_at", "reported_at")
    list_filter = ("status", "doctor")
    search_fields = ("patient__full_name", "patient__uhid")
    readonly_fields = ("created_at", "updated_at", "reported_at")
