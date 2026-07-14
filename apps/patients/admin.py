from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import (
    ChronicCondition,
    Patient,
    PatientAllergy,
    PatientDocument,
    PatientSequence,
)


class PatientAllergyInline(admin.TabularInline):
    model = PatientAllergy
    extra = 0


class ChronicConditionInline(admin.TabularInline):
    model = ChronicCondition
    extra = 0


@admin.register(Patient)
class PatientAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    inlines = [PatientAllergyInline, ChronicConditionInline]
    list_display = ("uhid", "full_name", "mobile", "sex", "created_at", "is_active")
    list_filter = ("sex", "preferred_language", "is_active", "dob_estimated")
    search_fields = ("uhid", "full_name", "mobile", "old_file_number")
    readonly_fields = (
        "id",
        "uhid",
        "name_normalized",
        "privacy_notice_version",
        "privacy_notice_accepted_at",
        "created_at",
        "updated_at",
    )


@admin.register(PatientSequence)
class PatientSequenceAdmin(admin.ModelAdmin):
    list_display = ("year", "last_value", "updated_at")
    readonly_fields = ("updated_at",)


@admin.register(PatientAllergy)
class PatientAllergyAdmin(admin.ModelAdmin):
    list_display = ("patient", "substance", "severity", "created_at")
    search_fields = ("patient__full_name", "patient__uhid", "substance")


@admin.register(ChronicCondition)
class ChronicConditionAdmin(admin.ModelAdmin):
    list_display = ("patient", "name", "created_at")
    search_fields = ("patient__full_name", "patient__uhid", "name")


@admin.register(PatientDocument)
class PatientDocumentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doc_type", "title", "uploaded_by", "uploaded_at")
    list_filter = ("doc_type",)
    search_fields = ("patient__full_name", "patient__uhid", "title")
    readonly_fields = ("uploaded_at",)

