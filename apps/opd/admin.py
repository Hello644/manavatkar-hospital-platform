from django.contrib import admin

from .models import Appointment, Receipt, ReceiptSequence, TokenSequence, Visit, VitalsRecord


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
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
class VitalsRecordAdmin(admin.ModelAdmin):
    list_display = ("visit", "weight_kg", "bp_systolic", "bp_diastolic", "pulse", "spo2")


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "date", "slot_time", "status")
    list_filter = ("date", "doctor", "status")
    search_fields = ("patient__full_name", "patient__uhid")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_no", "visit", "amount", "mode", "is_refunded", "created_at")
    list_filter = ("mode", "is_refunded")
    search_fields = ("receipt_no", "visit__patient__full_name")


admin.site.register(TokenSequence)
admin.site.register(ReceiptSequence)
