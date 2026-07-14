from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import (
    Appointment,
    ConsultationNote,
    Receipt,
    ReceiptSequence,
    TokenSequence,
    Visit,
    VitalsRecord,
)


@admin.register(Visit)
class VisitAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = (
        "token_label",
        "visit_date",
        "patient",
        "doctor",
        "status",
        "is_emergency",
        "is_mlc",
        "disposition",
    )
    list_filter = ("visit_date", "status", "doctor", "is_mlc", "is_emergency")
    search_fields = ("token_label", "patient__full_name", "patient__uhid")
    readonly_fields = ("registered_at", "called_at", "consult_started_at", "completed_at")


@admin.register(VitalsRecord)
class VitalsRecordAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("visit", "weight_kg", "bp_systolic", "bp_diastolic", "pulse", "spo2")


@admin.register(ConsultationNote)
class ConsultationNoteAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("visit", "diagnosis", "recorded_by", "recorded_at")
    search_fields = ("visit__patient__full_name", "diagnosis")
    readonly_fields = ("recorded_at", "updated_at")


@admin.register(Appointment)
class AppointmentAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("patient", "doctor", "date", "slot_time", "status")
    list_filter = ("date", "doctor", "status")
    search_fields = ("patient__full_name", "patient__uhid")


@admin.register(Receipt)
class ReceiptAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("receipt_no", "visit", "amount", "mode", "is_refunded", "created_at")
    list_filter = ("mode", "is_refunded")
    search_fields = ("receipt_no", "visit__patient__full_name")


admin.site.register(TokenSequence)
admin.site.register(ReceiptSequence)
