from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient

User = get_user_model()

DEMO_USERS = [
    ("rajesh", "doctor", True),
    ("madhu", "doctor", False),
    ("reception", "receptionist", False),
    ("sister", "nurse", False),
]

DEMO_PATIENTS = [
    ("Sita Ramesh Patil", "9876543210", "F", 34),
    ("Balu Kisan More", "9822011223", "M", 61),
    ("Anjali Deepak Chaudhari", "9922334455", "F", 8),
]


class Command(BaseCommand):
    help = "Seed demo users, the two doctor profiles, and sample patients (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo1234")
        parser.add_argument("--with-patients", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs with DJANGO_DEBUG=true (training/dev).")
        password = options["password"]

        for username, role, superuser in DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"is_staff": superuser, "is_superuser": superuser},
            )
            if created:
                user.set_password(password)
                user.save()
            user.groups.add(Group.objects.get(name=role))
            self.stdout.write(f"user {username} ({role}){' [new]' if created else ''}")

        rajesh = User.objects.get(username="rajesh")
        madhu = User.objects.get(username="madhu")
        DoctorProfile.objects.get_or_create(
            user=rajesh,
            defaults={
                "display_name": "Dr. Rajesh Manavatkar",
                "qualifications": "M.D. Medicine (Pune)",
                "specialty": "General Medicine",
                "state_medical_council": "Maharashtra Medical Council",
                "registration_number": "80166",
                "room_label": "A",
                "consult_fee": Decimal("200"),
                "prescription_enabled": True,
            },
        )
        DoctorProfile.objects.get_or_create(
            user=madhu,
            defaults={
                "display_name": "Dr. Madhu Rajesh Manavatkar",
                "qualifications": "M.B.B.S., D.G.O.",
                "specialty": "Gynecology",
                "state_medical_council": "Maharashtra Medical Council",
                "registration_number": "82243",
                "room_label": "B",
                "consult_fee": Decimal("200"),
                "prescription_enabled": True,
            },
        )
        self.stdout.write("doctor profiles ensured (Dr. Rajesh — A, Dr. Madhu — B)")

        if options["with_patients"]:
            for name, mobile, sex, age in DEMO_PATIENTS:
                if Patient.objects.filter(mobile=mobile).exists():
                    continue
                Patient.objects.create(
                    full_name=name,
                    mobile=mobile,
                    sex=sex,
                    age_years_at_registration=age,
                    privacy_notice_accepted=True,
                    guardian_name="Deepak Chaudhari" if age < 18 else "",
                    guardian_relationship="Father" if age < 18 else "",
                )
            self.stdout.write(f"{len(DEMO_PATIENTS)} demo patients ensured")

        self.stdout.write(
            self.style.SUCCESS(f"Done. Demo password for all users: {password}")
        )
