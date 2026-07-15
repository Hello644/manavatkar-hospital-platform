from datetime import time

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.attendance.models import LeaveType, Shift, StaffProfile
from apps.attendance import services

User = get_user_model()

SHIFTS = [
    ("Morning", time(8, 0), time(16, 0)),
    ("Evening", time(14, 0), time(22, 0)),
    ("Night", time(22, 0), time(6, 0)),
]
LEAVE_TYPES = [("Casual", True, 12), ("Sick", True, 12), ("Unpaid", False, 0)]


class Command(BaseCommand):
    help = "Seed demo shifts, leave types, and staff profiles for existing users."

    def handle(self, *args, **options):
        for name, start, end in SHIFTS:
            Shift.objects.get_or_create(name=name, defaults={"start_time": start, "end_time": end})
        for name, paid, days in LEAVE_TYPES:
            LeaveType.objects.get_or_create(name=name, defaults={"is_paid": paid, "default_days": days})

        made = 0
        for user in User.objects.filter(is_active=True):
            if user.groups.filter(name__in=["nurse", "receptionist", "staff"]).exists():
                _obj, created = StaffProfile.objects.get_or_create(
                    user=user, defaults={"designation": user.groups.first().name.title()}
                )
                made += 1 if created else 0

        morning = Shift.objects.get(name="Morning")
        from django.utils import timezone
        for staff in StaffProfile.objects.filter(is_active=True):
            services.make_shift_instance(staff, morning, timezone.localdate())

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Shift.objects.count()} shifts, {LeaveType.objects.count()} leave types, "
                f"{made} new staff profiles, and today's morning roster."
            )
        )
