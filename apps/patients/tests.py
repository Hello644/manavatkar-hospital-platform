import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import PatientForm
from .models import Patient, PatientDocument
from .services import generate_uhid, luhn_is_valid

User = get_user_model()


class UhidTests(TestCase):
    @override_settings(HOSPITAL_UHID_CODE="DMH")
    def test_generate_uhid_uses_code_year_sequence_and_valid_check_digit(self):
        uhid = generate_uhid()
        _code, _year, serial, check = uhid.split("-")

        self.assertEqual(uhid[:3], "DMH")
        self.assertEqual(serial, "000001")
        self.assertTrue(luhn_is_valid(f"{uhid.split('-')[1]}{serial}{check}"))


class PatientFormTests(TestCase):
    def base_data(self):
        return {
            "full_name": "Test Patient",
            "mobile": "9822012345",
            "no_phone": "",
            "age_years": "32",
            "dob": "",
            "sex": Patient.Sex.MALE,
            "address_line": "",
            "area_village": "",
            "city": "Bhusawal",
            "district": "Jalgaon",
            "pincode": "",
            "old_file_number": "",
            "guardian_name": "",
            "guardian_relationship": "",
            "preferred_language": Patient.PreferredLanguage.MARATHI,
            "abha_number": "",
            "abha_address": "",
            "blood_group": "",
            "email": "",
            "aadhaar_last4": "",
            "emergency_contact_name": "",
            "emergency_contact_phone": "",
            "referral_source": "",
            "privacy_notice_accepted": "on",
        }

    def test_valid_adult_registration_with_age(self):
        form = PatientForm(data=self.base_data())

        self.assertTrue(form.is_valid(), form.errors)
        patient = form.save()
        self.assertTrue(patient.uhid)
        self.assertTrue(patient.dob_estimated)

    def test_minor_requires_guardian(self):
        data = self.base_data()
        data["age_years"] = "8"
        form = PatientForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("guardian_name", form.errors)

    def test_minor_via_dob_requires_guardian(self):
        data = self.base_data()
        data["age_years"] = ""
        data["dob"] = (timezone.localdate() - timedelta(days=10 * 365)).isoformat()
        form = PatientForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("guardian_name", form.errors)

    def test_adult_via_dob_is_valid(self):
        data = self.base_data()
        data["age_years"] = ""
        data["dob"] = (timezone.localdate() - timedelta(days=30 * 365)).isoformat()
        form = PatientForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)

    def test_model_clean_blocks_minor_without_guardian(self):
        patient = Patient(
            full_name="Baby Patil",
            mobile="9822012399",
            sex=Patient.Sex.MALE,
            age_years_at_registration=6,
            privacy_notice_accepted=True,
        )
        with self.assertRaises(ValidationError):
            patient.full_clean()

    def test_mobile_required_unless_no_phone(self):
        data = self.base_data()
        data["mobile"] = ""
        form = PatientForm(data=data)

        self.assertFalse(form.is_valid())
        self.assertIn("mobile", form.errors)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class PatientDocumentTests(TestCase):
    def setUp(self):
        self.patient = Patient.objects.create(
            full_name="Doc Patient", mobile="9812345678", sex=Patient.Sex.MALE,
            age_years_at_registration=40, privacy_notice_accepted=True,
        )
        self.receptionist = User.objects.create_user(username="recept", password="x")
        self.receptionist.groups.add(Group.objects.get(name="receptionist"))
        self.pharmacist = User.objects.create_user(username="pharma", password="x")
        self.pharmacist.groups.add(Group.objects.get(name="pharmacist"))

    def _upload(self, name="report.pdf", content=b"%PDF-1.4 test"):
        return self.client.post(
            reverse("patients:document_upload", args=[self.patient.pk]),
            {"file": SimpleUploadedFile(name, content), "doc_type": "lab", "title": "CBC"},
        )

    def test_clinical_role_uploads_and_downloads(self):
        self.client.force_login(self.receptionist)
        self._upload()
        doc = PatientDocument.objects.get()
        self.assertEqual(doc.patient, self.patient)
        self.assertEqual(doc.uploaded_by, self.receptionist)
        response = self.client.get(reverse("patients:document_download", args=[doc.id]))
        self.assertEqual(response.status_code, 200)

    def test_bad_extension_rejected(self):
        self.client.force_login(self.receptionist)
        self._upload(name="malware.exe", content=b"MZ")
        self.assertEqual(PatientDocument.objects.count(), 0)

    def test_pharmacist_cannot_download(self):
        self.client.force_login(self.receptionist)
        self._upload()
        doc = PatientDocument.objects.get()
        self.client.force_login(self.pharmacist)
        response = self.client.get(reverse("patients:document_download", args=[doc.id]))
        self.assertEqual(response.status_code, 403)

