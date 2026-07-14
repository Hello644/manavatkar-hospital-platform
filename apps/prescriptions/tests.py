from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.opd import services as opd_services
from apps.patients.models import Patient, PatientAllergy

from . import services
from .models import Drug, Prescription

User = get_user_model()


def make_doctor(username="drrajesh", prescribe=True):
    user = User.objects.create_user(username=username, password="pass12345")
    user.groups.add(Group.objects.get(name="doctor"))
    return DoctorProfile.objects.create(
        user=user,
        display_name="Dr. Rajesh",
        registration_number="80166" if prescribe else "",
        prescription_enabled=prescribe,
        room_label="A",
        consult_fee=Decimal("200"),
    )


def make_patient(name="Sita Patil"):
    return Patient.objects.create(
        full_name=name, mobile="9876543210", sex=Patient.Sex.FEMALE,
        age_years_at_registration=30, privacy_notice_accepted=True,
    )


class DosageParsingTests(TestCase):
    def test_shorthand_to_doses_per_day(self):
        self.assertEqual(services.doses_per_day("1-0-1"), 2)
        self.assertEqual(services.doses_per_day("1-1-1"), 3)
        self.assertEqual(services.doses_per_day("BD"), 2)
        self.assertEqual(services.doses_per_day("TDS"), 3)
        self.assertEqual(services.doses_per_day("OD"), 1)
        self.assertEqual(services.doses_per_day("SOS"), 0)

    def test_computed_quantity(self):
        self.assertEqual(services.computed_quantity("1-0-1", 5), 10)
        self.assertEqual(services.computed_quantity("1-1-1", 3), 9)
        self.assertIsNone(services.computed_quantity("SOS", 5))


class CreatePrescriptionTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.user = self.doctor.user
        self.drug = Drug.objects.create(
            generic_name="Amoxicillin", brand_name="Mox", strength="500 mg",
            form="capsule", ingredients="amoxicillin",
        )

    def test_create_computes_quantity_and_bumps_usage(self):
        rx = services.create_prescription(
            patient=self.patient, doctor=self.doctor, user=self.user,
            item_specs=[{"drug": self.drug, "drug_text": self.drug.label,
                         "dosage": "1-0-1", "duration_days": 5}],
        )
        item = rx.items.get()
        self.assertEqual(item.quantity, 10)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.usage_count, 1)

    def test_free_text_item_allowed(self):
        rx = services.create_prescription(
            patient=self.patient, doctor=self.doctor, user=self.user,
            item_specs=[{"drug": None, "drug_text": "Cough syrup 10ml", "dosage": "TDS"}],
        )
        self.assertEqual(rx.items.get().drug_text, "Cough syrup 10ml")

    def test_allergy_conflict_detected(self):
        PatientAllergy.objects.create(patient=self.patient, substance="Amoxicillin")
        conflicts = services.allergy_conflicts(
            self.patient, [{"drug": self.drug, "drug_text": self.drug.label}]
        )
        self.assertTrue(conflicts)


class ComposerViewTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.drug = Drug.objects.create(
            generic_name="Paracetamol", brand_name="Dolo", strength="650 mg",
            form="tablet", ingredients="paracetamol",
        )
        self.visit, _ = opd_services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.doctor.user
        )

    def _post(self, extra=None):
        data = {
            "diagnosis": "Fever",
            "drug_text": ["PARACETAMOL (Dolo) 650 mg"],
            "dosage": ["1-0-1"],
            "duration_days": ["5"],
            "instructions": ["after food"],
        }
        if extra:
            data.update(extra)
        return self.client.post(reverse("prescriptions:compose", args=[self.visit.pk]), data)

    def test_doctor_can_write_prescription(self):
        self.client.force_login(self.doctor.user)
        response = self._post()
        rx = Prescription.objects.get()
        self.assertRedirects(response, reverse("prescriptions:detail", args=[rx.pk]))
        self.assertEqual(rx.items.get().quantity, 10)
        self.assertEqual(rx.visit_id, self.visit.pk)

    def test_allergy_blocks_without_override(self):
        PatientAllergy.objects.create(patient=self.patient, substance="Paracetamol")
        self.client.force_login(self.doctor.user)
        response = self._post()
        self.assertEqual(response.status_code, 200)  # re-rendered, not saved
        self.assertEqual(Prescription.objects.count(), 0)
        # With an override reason it proceeds.
        response = self._post({"allergy_override_reason": "Benefit outweighs risk"})
        self.assertEqual(Prescription.objects.count(), 1)

    def test_non_prescriber_blocked(self):
        weak = make_doctor("drlocum", prescribe=False)
        visit, _ = opd_services.create_visit(
            patient=self.patient, doctor=weak, user=weak.user
        )
        self.client.force_login(weak.user)
        response = self.client.get(reverse("prescriptions:compose", args=[visit.pk]))
        self.assertRedirects(response, reverse("opd:visit_detail", args=[visit.pk]))
        self.assertEqual(Prescription.objects.count(), 0)

    def test_receptionist_cannot_compose(self):
        recept = User.objects.create_user(username="recept", password="x")
        recept.groups.add(Group.objects.get(name="receptionist"))
        self.client.force_login(recept)
        response = self.client.get(reverse("prescriptions:compose", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 403)

    def test_print_view_renders(self):
        self.client.force_login(self.doctor.user)
        self._post()
        rx = Prescription.objects.get()
        response = self.client.get(reverse("prescriptions:print", args=[rx.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reg. No.")
