from django.core.exceptions import ValidationError
from django.test import TestCase

from .forms import PinSwitchForm
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


class PinLockoutTests(TestCase):
    def _pin_user(self, username="nurse2", pin="123456"):
        user = User.objects.create_user(username=username, password="test-pass")
        user.set_pin(pin)
        user.save()
        return user

    def _switch_form(self, user, pin):
        return PinSwitchForm(data={"user_id": str(user.pk), "pin": pin})

    def test_five_wrong_pins_lock_then_correct_pin_is_refused(self):
        user = self._pin_user()
        for _ in range(5):
            self.assertFalse(self._switch_form(user, "000000").is_valid())
        # The account is now locked: even the correct PIN is rejected.
        form = self._switch_form(user, "123456")
        self.assertFalse(form.is_valid())
        user.refresh_from_db()
        self.assertTrue(user.is_pin_locked())

    def test_success_resets_failure_counter(self):
        user = self._pin_user()
        user.register_pin_failure()
        user.register_pin_failure()
        user.refresh_from_db()
        self.assertEqual(user.failed_pin_attempts, 2)
        user.reset_pin_failures()
        user.refresh_from_db()
        self.assertEqual(user.failed_pin_attempts, 0)
        self.assertFalse(user.is_pin_locked())

    def test_lockout_is_per_user(self):
        locked = self._pin_user("locked_user")
        other = self._pin_user("other_user")
        for _ in range(5):
            self._switch_form(locked, "000000").is_valid()
        locked.refresh_from_db()
        other.refresh_from_db()
        self.assertTrue(locked.is_pin_locked())
        self.assertFalse(other.is_pin_locked())
        self.assertTrue(self._switch_form(other, "123456").is_valid())


class ForcePinChangeTests(TestCase):
    def test_must_change_pin_holds_user_on_set_pin(self):
        from django.urls import reverse

        user = User.objects.create_user(username="forced", password="test-pass")
        user.must_change_pin = True
        user.save()
        self.client.force_login(user)

        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:set_pin"), response["Location"])
        # The set-PIN page itself stays reachable.
        self.assertEqual(self.client.get(reverse("accounts:set_pin")).status_code, 200)


class DoctorProfileTests(TestCase):
    def test_prescribing_requires_registration_number(self):
        user = User.objects.create_user(username="doctor1", password="test-pass")
        profile = DoctorProfile(
            user=user, display_name="Dr Test", prescription_enabled=True
        )

        with self.assertRaises(ValidationError):
            profile.full_clean()

