from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import DoctorProfile, User


class UserPinTests(TestCase):
    def test_pin_must_be_six_digits(self):
        user = User(username="nurse1")
        with self.assertRaises(ValidationError):
            user.set_pin("12345")

    def test_pin_is_hashed_and_checkable(self):
        user = User.objects.create_user(username="reception1", password="test-pass")
        user.set_pin("123456")
        user.save()

        self.assertNotEqual(user.pin_hash, "123456")
        self.assertTrue(user.check_pin("123456"))
        self.assertFalse(user.check_pin("000000"))


class DoctorProfileTests(TestCase):
    def test_prescribing_requires_registration_number(self):
        user = User.objects.create_user(username="doctor1", password="test-pass")
        profile = DoctorProfile(
            user=user, display_name="Dr Test", prescription_enabled=True
        )

        with self.assertRaises(ValidationError):
            profile.full_clean()

