from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import DoctorProfile, User


class DoctorProfileInline(admin.StackedInline):
    model = DoctorProfile
    can_delete = False
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = [DoctorProfileInline]
    list_display = (
        "username",
        "employee_code",
        "first_name",
        "last_name",
        "is_staff",
        "is_active",
    )
    list_filter = DjangoUserAdmin.list_filter
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Hospital account", {"fields": ("employee_code", "mobile", "must_change_pin")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Hospital account", {"fields": ("employee_code", "mobile")}),
    )


@admin.register(DoctorProfile)
class DoctorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "registration_number",
        "state_medical_council",
        "specialty",
        "prescription_enabled",
        "is_locum",
    )
    list_filter = ("prescription_enabled", "is_locum", "specialty")
    search_fields = ("display_name", "registration_number", "user__username")
