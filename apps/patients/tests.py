from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from .forms import PatientForm
from .models import Patient
from .services import generate_uhid, luhn_is_valid


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

