from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import DoctorProfile
from apps.opd import services as opd_services
from apps.patients.models import Patient

from . import services
from .models import LabOrder, LabTest

User = get_user_model()


def make_doctor():
    user = User.objects.create_user(username="drrajesh", password="x")
    user.groups.add(Group.objects.get(name="doctor"))
    return DoctorProfile.objects.create(
        user=user, display_name="Dr. Rajesh", registration_number="80166",
        room_label="A", consult_fee=Decimal("200"),
    )


def make_patient():
    return Patient.objects.create(
        full_name="Sita Patil", mobile="9876543210", sex=Patient.Sex.FEMALE,
        age_years_at_registration=30, privacy_notice_accepted=True,
    )


class LabOrderServiceTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.cbc = LabTest.objects.create(name="Complete Blood Count", short_code="CBC")

    def test_create_order_resolves_catalog_and_free_text(self):
        order = services.create_lab_order(
            patient=self.patient, doctor=self.doctor, user=self.doctor.user,
            test_specs=[{"test": self.cbc, "test_text": self.cbc.label},
                        {"test": None, "test_text": "Peripheral smear"}],
        )
        self.assertEqual(order.items.count(), 2)
        self.cbc.refresh_from_db()
        self.assertEqual(self.cbc.usage_count, 1)

    def test_save_results_marks_reported(self):
        order = services.create_lab_order(
            patient=self.patient, doctor=self.doctor, user=self.doctor.user,
            test_specs=[{"test": self.cbc, "test_text": self.cbc.label}],
        )
        item = order.items.get()
        services.save_results(
            order, {str(item.pk): {"result_value": "13.5", "flag": "normal"}},
            mark_reported=True,
        )
        order.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(order.status, LabOrder.Status.REPORTED)
        self.assertIsNotNone(order.reported_at)
        self.assertEqual(item.result_value, "13.5")


class LabOrderViewTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.nurse = User.objects.create_user(username="nurse1", password="x")
        self.nurse.groups.add(Group.objects.get(name="nurse"))
        self.visit, _ = opd_services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.doctor.user
        )
        LabTest.objects.create(name="Random Blood Sugar", short_code="RBS")

    def test_doctor_places_order(self):
        self.client.force_login(self.doctor.user)
        response = self.client.post(
            reverse("lab:order_create", args=[self.visit.pk]),
            {"indication": "fever", "test_text": ["Random Blood Sugar (RBS)", ""]},
        )
        order = LabOrder.objects.get()
        self.assertRedirects(response, reverse("lab:detail", args=[order.pk]))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.visit_id, self.visit.pk)

    def test_nurse_enters_results(self):
        order = services.create_lab_order(
            patient=self.patient, doctor=self.doctor, user=self.doctor.user, visit=self.visit,
            test_specs=[{"test": None, "test_text": "RBS"}],
        )
        item = order.items.get()
        self.client.force_login(self.nurse)
        response = self.client.post(
            reverse("lab:save_results", args=[order.pk]),
            {f"value_{item.pk}": "180", f"flag_{item.pk}": "high", "report": "1"},
        )
        self.assertRedirects(response, reverse("lab:detail", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.status, LabOrder.Status.REPORTED)

    def test_other_doctor_cannot_order(self):
        other_user = User.objects.create_user(username="drother", password="x")
        other_user.groups.add(Group.objects.get(name="doctor"))
        DoctorProfile.objects.create(
            user=other_user, display_name="Dr. Other", registration_number="1", room_label="C",
        )
        self.client.force_login(other_user)
        response = self.client.get(reverse("lab:order_create", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 403)
