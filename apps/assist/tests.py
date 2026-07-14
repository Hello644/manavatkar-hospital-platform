from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import DoctorProfile
from apps.opd import services as opd_services
from apps.opd.models import VitalsRecord
from apps.patients.models import Patient, PatientAllergy

from . import services
from .models import AiInteraction

User = get_user_model()


class AssistServiceTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="drrajesh", password="x")
        user.groups.add(Group.objects.get(name="doctor"))
        self.doctor = DoctorProfile.objects.create(
            user=user, display_name="Dr. Rajesh", registration_number="80166",
            room_label="A", consult_fee=Decimal("200"),
        )
        self.patient = Patient.objects.create(
            full_name="Sita Secret Patil", mobile="9876543210", sex=Patient.Sex.FEMALE,
            age_years_at_registration=30, privacy_notice_accepted=True,
        )
        self.visit, _ = opd_services.create_visit(
            patient=self.patient, doctor=self.doctor, user=user
        )
        VitalsRecord.objects.create(visit=self.visit, pulse=88, bp_systolic=120, bp_diastolic=80)
        PatientAllergy.objects.create(patient=self.patient, substance="Penicillin")

    def test_disabled_by_default(self):
        self.assertFalse(services.is_available())

    def test_context_is_deidentified(self):
        ctx = services.build_context(self.visit)
        # Direct identifiers must not be sent to the external model.
        self.assertNotIn("Sita", ctx)
        self.assertNotIn(self.patient.uhid, ctx)
        self.assertNotIn("9876543210", ctx)
        # Clinical facts are present.
        self.assertIn("Penicillin", ctx)
        self.assertIn("pulse 88", ctx)

    def test_view_degrades_without_api_key(self):
        self.client.force_login(self.doctor.user)
        response = self.client.get(reverse("assist:assist_visit", args=[self.visit.pk, "summary"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not configured")
        self.assertEqual(AiInteraction.objects.count(), 0)  # no external call made

    def test_receptionist_blocked(self):
        recept = User.objects.create_user(username="recept", password="x")
        recept.groups.add(Group.objects.get(name="receptionist"))
        self.client.force_login(recept)
        response = self.client.get(reverse("assist:assist_visit", args=[self.visit.pk, "summary"]))
        self.assertEqual(response.status_code, 403)

    @override_settings(OPD_AI_ENABLED=True, OPD_ANTHROPIC_API_KEY="")
    def test_enabled_but_no_key_still_unavailable(self):
        self.assertFalse(services.is_available())
