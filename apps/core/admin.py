from django.contrib import admin

from .models import HospitalProfile


@admin.register(HospitalProfile)
class HospitalProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "updated_at")

    def has_add_permission(self, request):
        # Singleton: only allow adding the first row.
        return not HospitalProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
