from django.contrib import admin

from apps.core.admin_mixins import NoHardDeleteAdminMixin

from .models import (
    AttendanceRecord,
    ConsentRecord,
    FaceEnrollment,
    LeaveRequest,
    LeaveType,
    PunchEvent,
    RegularizationRequest,
    Shift,
    ShiftInstance,
    ShiftSwapRequest,
    StaffProfile,
)


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("display_name", "designation", "department", "is_punch_exempt", "is_active")
    list_filter = ("department", "is_punch_exempt", "is_active")
    search_fields = ("user__first_name", "user__last_name", "user__username", "designation")


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time", "crosses_midnight", "grace_minutes", "is_active")


@admin.register(ShiftInstance)
class ShiftInstanceAdmin(admin.ModelAdmin):
    list_display = ("staff", "shift", "date", "status", "is_on_duty")
    list_filter = ("status", "date", "shift")
    search_fields = ("staff__user__first_name", "staff__user__username")


@admin.register(PunchEvent)
class PunchEventAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("staff", "event_time", "source", "confidence", "device")
    list_filter = ("source",)
    readonly_fields = ("created_at",)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("shift_instance", "first_in", "last_out", "status", "worked_minutes")
    list_filter = ("status",)


@admin.register(ConsentRecord)
class ConsentRecordAdmin(NoHardDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("staff", "method", "consent_given", "recorded_at", "withdrawn_at")
    list_filter = ("method", "consent_given")


@admin.register(FaceEnrollment)
class FaceEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("staff", "quality", "is_active", "enrolled_at")


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "is_paid", "default_days")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("staff", "leave_type", "from_date", "to_date", "status")
    list_filter = ("status", "leave_type")


@admin.register(ShiftSwapRequest)
class ShiftSwapRequestAdmin(admin.ModelAdmin):
    list_display = ("shift_instance", "to_staff", "status")


@admin.register(RegularizationRequest)
class RegularizationRequestAdmin(admin.ModelAdmin):
    list_display = ("shift_instance", "status", "created_at", "resolved_at")
    list_filter = ("status",)
