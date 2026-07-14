from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import Drug, Prescription, PrescriptionItem


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    list_display = ("generic_name", "brand_name", "strength", "form", "schedule", "usage_count", "is_active")
    list_filter = ("schedule", "form", "is_active")
    search_fields = ("generic_name", "brand_name", "ingredients")


class PrescriptionItemInline(admin.TabularInline):
    model = PrescriptionItem
    extra = 0


@admin.register(Prescription)
class PrescriptionAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    inlines = [PrescriptionItemInline]
    list_display = ("short_id", "patient", "doctor", "status", "created_at")
    list_filter = ("status", "doctor")
    search_fields = ("patient__full_name", "patient__uhid", "diagnosis")
    readonly_fields = ("created_at",)
