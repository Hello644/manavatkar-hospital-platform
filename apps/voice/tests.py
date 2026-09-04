from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.opd.models import Appointment
from apps.patients.models import Patient

from . import agent, tools
from .models import CallSession

User = get_user_model()


def next_full_opd_day():
    """Next date running BOTH sittings. Tests must not depend on what day they
    are run — evening OPD is closed Tuesday and Saturday, so a bare
    "tomorrow" silently breaks the suite twice a week."""
    from apps.opd.booking import EVENING_CLOSED

    d = timezone.localdate() + timedelta(days=1)
    while d.weekday() in EVENING_CLOSED:
        d += timedelta(days=1)
    return d


def make_doctor(name="Dr. Madhu Manavatkar", specialty="Gynecology"):
    user = User.objects.create_user(username=name.split()[-1].lower(), password="x")
    return DoctorProfile.objects.create(
        user=user, display_name=name, specialty=specialty, registration_number="82243",
        room_label="B", consult_fee=Decimal("300"),
    )


class BookingToolTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = next_full_opd_day().isoformat()

    def test_available_sessions_lists_the_sittings_that_run(self):
        result = tools.available_sessions("Madhu", self.tomorrow)
        self.assertTrue(result["ok"])
        self.assertEqual([s["key"] for s in result["sessions"]], ["morning", "evening"])
        self.assertEqual(result["sessions"][0]["time"], "10:00–15:00")

    def test_book_creates_provisional_patient_and_appointment(self):
        result = tools.book_appointment("Ravi Kumar", "9876543210", "gynec", self.tomorrow, "morning")
        self.assertTrue(result["ok"], result)
        appt = Appointment.objects.get()
        self.assertEqual(appt.doctor, self.doctor)
        self.assertEqual(appt.patient.mobile, "9876543210")
        self.assertTrue(appt.patient.privacy_notice_deferred)

    def test_book_reuses_existing_patient_by_mobile(self):
        existing = Patient.objects.create(
            full_name="Sita", mobile="9876543210", sex="F",
            age_years_at_registration=30, privacy_notice_accepted=True,
        )
        tools.book_appointment("Sita", "9876543210", "Madhu", self.tomorrow, "evening")
        self.assertEqual(Patient.objects.filter(mobile="9876543210").count(), 1)
        self.assertEqual(Appointment.objects.get().patient, existing)

    def test_second_booking_in_the_same_sitting_is_allowed(self):
        """No numbered slots: the sitting has unlimited capacity."""
        tools.book_appointment("Anil", "9876543210", "Madhu", self.tomorrow, "morning")
        result = tools.book_appointment("Bhaskar", "9812345678", "Madhu", self.tomorrow, "morning")
        self.assertTrue(result["ok"], result)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_book_rejects_bad_mobile(self):
        result = tools.book_appointment("Anil", "123", "Madhu", self.tomorrow, "morning")
        self.assertFalse(result["ok"])

    def test_book_rejects_off_grid_and_lunch_times(self):
        # 10:05 is not on the slot grid; 14:00 is between the OPD windows.
        self.assertFalse(tools.book_appointment("A", "9876543210", "Madhu", self.tomorrow, "10:05")["ok"])
        self.assertFalse(tools.book_appointment("A", "9876543210", "Madhu", self.tomorrow, "14:00")["ok"])

    def test_provisional_patient_is_valid_and_flagged(self):
        tools.book_appointment("Ravi", "9876500000", "Madhu", self.tomorrow, "morning")
        patient = Patient.objects.get(mobile="9876500000")
        self.assertEqual(patient.sex, Patient.Sex.OTHER)
        self.assertTrue(patient.is_unknown)

    def test_book_handles_missing_name(self):
        result = tools.book_appointment(None, "9876500011", "Madhu", self.tomorrow, "morning")
        self.assertTrue(result["ok"], result)
        self.assertEqual(Patient.objects.get(mobile="9876500011").full_name, "Phone booking")


# ---- Fake Anthropic client for the tool-use loop --------------------------

def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(tid, name, tool_input):
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=tool_input)


class FakeMessages:
    def __init__(self, script):
        self.script, self.i = script, 0

    def create(self, **kwargs):
        resp = self.script[self.i]
        self.i += 1
        return resp


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


class AgentLoopTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.session = CallSession.objects.create(call_sid="CA1", from_number="+919876543210")
        self.tomorrow = next_full_opd_day().isoformat()

    def test_loop_books_and_ends(self):
        script = [
            SimpleNamespace(stop_reason="tool_use", content=[
                _tool("t1", "book_appointment", {
                    "patient_name": "Ravi", "mobile": "9876543210",
                    "doctor_name": "Madhu", "date_str": self.tomorrow, "session_key": "morning",
                }),
            ]),
            SimpleNamespace(stop_reason="tool_use", content=[
                _text("Booked with Dr. Madhu tomorrow at 11. See you then."),
                _tool("t2", "end_call", {"reason": "done"}),
            ]),
        ]
        reply, done = agent.respond(self.session, "book me with the gynec doctor", client=FakeClient(script))
        self.assertTrue(done)
        self.assertIn("Booked", reply)
        self.session.refresh_from_db()
        self.assertIsNotNone(self.session.booked_appointment_id)
        self.assertEqual(Appointment.objects.count(), 1)


@override_settings(DEBUG=True)  # dev skip-verification path; fail-closed tested separately
class WebhookTests(TestCase):
    def setUp(self):
        make_doctor()

    def test_incoming_no_agent_hangs_up(self):
        resp = self.client.post(reverse("voice:incoming"), {"CallSid": "CA9", "From": "+9199"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("<Hangup", resp.content.decode())
        self.assertEqual(CallSession.objects.get().status, CallSession.Status.NO_AGENT)

    @patch("apps.voice.agent.is_available", return_value=True)
    def test_incoming_greets_and_gathers(self, _mock):
        resp = self.client.post(reverse("voice:incoming"), {"CallSid": "CA2", "From": "+9199"})
        self.assertIn("<Gather", resp.content.decode())

    @patch("apps.voice.agent.respond", return_value=("Which doctor would you like?", False))
    def test_turn_continues_conversation(self, _mock):
        CallSession.objects.create(call_sid="CA3")
        resp = self.client.post(reverse("voice:turn"), {"CallSid": "CA3", "SpeechResult": "I want an appointment"})
        body = resp.content.decode()
        self.assertIn("<Gather", body)
        self.assertIn("Which doctor", body)

    @patch("apps.voice.agent.respond", return_value=("Booked, goodbye.", True))
    def test_turn_hangs_up_when_done(self, _mock):
        CallSession.objects.create(call_sid="CA4")
        resp = self.client.post(reverse("voice:turn"), {"CallSid": "CA4", "SpeechResult": "yes book it"})
        self.assertIn("<Hangup", resp.content.decode())
        self.assertEqual(CallSession.objects.get(call_sid="CA4").status, CallSession.Status.COMPLETED)

    @override_settings(TWILIO_AUTH_TOKEN="secret")
    def test_bad_signature_rejected(self):
        resp = self.client.post(
            reverse("voice:incoming"), {"CallSid": "CA5"}, HTTP_X_TWILIO_SIGNATURE="wrong"
        )
        self.assertEqual(resp.status_code, 403)

    @override_settings(DEBUG=False, TWILIO_AUTH_TOKEN="", ALLOWED_HOSTS=["testserver"])
    def test_webhook_fails_closed_in_prod_without_token(self):
        # No token + not DEBUG must REJECT (not accept) — the critical fail-open fix.
        resp = self.client.post(reverse("voice:incoming"), {"CallSid": "CA6"})
        self.assertEqual(resp.status_code, 403)
