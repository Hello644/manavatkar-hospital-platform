from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import DoctorProfile
from apps.opd import services as opd_services
from apps.patients.models import Patient
from apps.prescriptions.models import Drug
from apps.prescriptions.services import create_prescription

from . import services
from .models import OutboundMessage

User = get_user_model()


class MsisdnTests(TestCase):
    def test_normalize(self):
        self.assertEqual(services.normalize_msisdn("+91 98765 43210"), "9876543210")
        self.assertEqual(services.normalize_msisdn("919876543210"), "9876543210")
        self.assertEqual(services.normalize_msisdn("9876543210"), "9876543210")

    def test_whatsapp_link(self):
        link = services.whatsapp_link("9876543210", "hi there")
        self.assertIn("wa.me/919876543210", link)
        self.assertIn("hi%20there", link)


class SharePrescriptionTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="drrajesh", password="x")
        user.groups.add(Group.objects.get(name="doctor"))
        self.doctor = DoctorProfile.objects.create(
            user=user, display_name="Dr. Rajesh", registration_number="80166",
            prescription_enabled=True, room_label="A", consult_fee=Decimal("200"),
        )
        self.patient = Patient.objects.create(
            full_name="Sita Patil", mobile="9876543210", sex=Patient.Sex.FEMALE,
            age_years_at_registration=30, privacy_notice_accepted=True,
        )
        self.receptionist = User.objects.create_user(username="recept", password="x")
        self.receptionist.groups.add(Group.objects.get(name="receptionist"))
        self.xdrug = Drug.objects.create(
            generic_name="Morphine", strength="10 mg", form="tablet",
            schedule=Drug.Schedule.X, ingredients="morphine",
        )

    def _rx(self, mlc=False, schedule_x=False):
        visit, _ = opd_services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist,
            is_mlc=mlc, mlc_police_station="Bhusawal PS" if mlc else "",
        )
        specs = [{"drug": self.xdrug if schedule_x else None,
                  "drug_text": "Morphine 10mg" if schedule_x else "Paracetamol", "dosage": "OD"}]
        return create_prescription(
            patient=self.patient, doctor=self.doctor, user=self.receptionist,
            visit=visit, item_specs=specs,
        )

    def test_share_logs_and_redirects_to_whatsapp(self):
        rx = self._rx()
        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse("comms:share_prescription", args=[rx.pk]),
            {"number": "9876543210", "confirm": "yes"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("wa.me/919876543210", response["Location"])
        msg = OutboundMessage.objects.get()
        self.assertEqual(msg.status, OutboundMessage.Status.SENT)
        self.assertEqual(msg.channel, OutboundMessage.Channel.WHATSAPP)

    def test_share_blocked_for_mlc(self):
        rx = self._rx(mlc=True)
        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse("comms:share_prescription", args=[rx.pk]),
            {"number": "9876543210", "confirm": "yes"},
        )
        self.assertRedirects(response, reverse("prescriptions:detail", args=[rx.pk]))
        self.assertEqual(OutboundMessage.objects.filter(status="blocked").count(), 1)
        self.assertEqual(OutboundMessage.objects.filter(status="sent").count(), 0)

    def test_share_blocked_for_schedule_x(self):
        rx = self._rx(schedule_x=True)
        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse("comms:share_prescription", args=[rx.pk]),
            {"number": "9876543210", "confirm": "yes"},
        )
        self.assertRedirects(response, reverse("prescriptions:detail", args=[rx.pk]))
        self.assertEqual(OutboundMessage.objects.filter(status="sent").count(), 0)

    def test_unconfirmed_number_does_not_send(self):
        rx = self._rx()
        self.client.force_login(self.receptionist)
        self.client.post(
            reverse("comms:share_prescription", args=[rx.pk]),
            {"number": "9876543210"},  # no confirm checkbox
        )
        self.assertEqual(OutboundMessage.objects.filter(status="sent").count(), 0)
