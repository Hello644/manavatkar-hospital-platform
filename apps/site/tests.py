from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.core.models import HospitalProfile
from apps.opd.models import Appointment
from apps.patients.models import Patient

from .models import Announcement, PublicBookingAttempt, Service

User = get_user_model()

PUBLIC_HOST = "manwatkarhospital.in"
LAN_HOST = "testserver"

# The live deployment shape: the domain serves the public site only, while the
# LAN hostname serves everything.
AS_DEPLOYED = override_settings(
    PUBLIC_SITE_HOSTS=[PUBLIC_HOST],
    ALLOWED_HOSTS=[PUBLIC_HOST, "www." + PUBLIC_HOST, LAN_HOST],
)


def make_doctor(name="Dr. Madhu Manwatkar", specialty="Gynecology", public=True, online=True):
    user = User.objects.create_user(username=name.split()[-1].lower() + specialty[:3].lower(),
                                    password="x")
    return DoctorProfile.objects.create(
        user=user, display_name=name, specialty=specialty, registration_number="82243",
        room_label="B", consult_fee=Decimal("300"),
        show_on_website=public, accepts_online_booking=online,
    )


class PublicPageTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.hidden = make_doctor("Dr. Private Consultant", "Dermatology",
                                  public=False, online=False)

    def test_home_is_public_and_shows_hospital_identity(self):
        HospitalProfile.objects.update_or_create(
            pk=1, defaults={"name": "Manwatkar Hospital", "tagline": "Care in Bhusawal"}
        )
        resp = self.client.get(reverse("site:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Manwatkar Hospital")
        self.assertContains(resp, "Care in Bhusawal")

    def test_doctors_page_lists_only_opted_in_doctors(self):
        resp = self.client.get(reverse("site:doctors"))
        self.assertContains(resp, "Dr. Madhu Manwatkar")
        self.assertNotContains(resp, "Dr. Private Consultant")

    def test_services_and_announcements_render_from_the_database(self):
        Service.objects.create(name="Maternity", name_marathi="प्रसूती", icon="🤱")
        Announcement.objects.create(title="Vaccination camp on Sunday")
        resp = self.client.get(reverse("site:home"))
        self.assertContains(resp, "Maternity")
        self.assertContains(resp, "Vaccination camp on Sunday")

    def test_expired_announcement_is_not_shown(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        Announcement.objects.create(
            title="Old notice", starts_on=yesterday - timedelta(days=5), ends_on=yesterday
        )
        resp = self.client.get(reverse("site:home"))
        self.assertNotContains(resp, "Old notice")

    def test_contact_and_services_pages_load(self):
        for name in ("site:contact", "site:services", "site:robots", "site:sitemap"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)


class BookingFlowTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def _slots(self):
        resp = self.client.get(
            reverse("site:book"), {"doctor": self.doctor.pk, "date": self.tomorrow.isoformat()}
        )
        return resp

    def test_picking_a_doctor_and_date_shows_free_times(self):
        resp = self._slots()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "10:00")
        self.assertContains(resp, "17:00")

    def test_booking_creates_appointment_and_provisional_patient(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:00", "full_name": "Ravi Kumar",
            "mobile": "9876543210", "reason": "fever", "website": "",
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        appointment = Appointment.objects.get()
        self.assertEqual(appointment.doctor, self.doctor)
        self.assertEqual(appointment.patient.mobile, "9876543210")
        self.assertIn("website", appointment.notes)
        self.assertIn("fever", appointment.notes)
        # Provisional until reception completes identity + DPDP consent.
        self.assertTrue(appointment.patient.is_unknown)
        self.assertTrue(appointment.patient.privacy_notice_deferred)
        self.assertContains(resp, "Ravi Kumar")
        self.assertContains(resp, "Dr. Madhu Manwatkar")

    def test_confirmation_is_not_replayable(self):
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:00", "full_name": "Ravi Kumar", "mobile": "9876543210",
        })
        # First view consumes it; a refresh must not re-print the details.
        self.client.get(reverse("site:book_done"))
        resp = self.client.get(reverse("site:book_done"))
        self.assertNotContains(resp, "Ravi Kumar")

    def test_slot_outside_opd_hours_is_refused(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "14:00", "full_name": "Ravi", "mobile": "9876543210",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_already_taken_slot_is_refused(self):
        patient = Patient.objects.create(
            full_name="A", mobile="9000000000", privacy_notice_deferred=True
        )
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, date=self.tomorrow, slot_time="11:00"
        )
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:00", "full_name": "B", "mobile": "9876543210",
        })
        self.assertEqual(Appointment.objects.count(), 1)

    def test_doctor_not_opted_into_online_booking_cannot_be_booked(self):
        offline = make_doctor("Dr. Offline Only", "ENT", public=True, online=False)
        self.client.post(reverse("site:book"), {
            "doctor": offline.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:00", "full_name": "B", "mobile": "9876543210",
        })
        self.assertEqual(Appointment.objects.count(), 0)

    def test_shared_family_mobile_does_not_book_onto_the_wrong_chart(self):
        """One number per household is normal here. A different name on the
        same number must get its own record, not the other person's chart."""
        husband = Patient.objects.create(
            full_name="Balu Kisan More", mobile="9822011223", sex="M",
            age_years_at_registration=52, privacy_notice_accepted=True,
        )
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:30", "full_name": "Sunita Patil", "mobile": "9822011223",
        })
        appointment = Appointment.objects.get()
        self.assertNotEqual(appointment.patient, husband)
        self.assertEqual(appointment.patient.full_name, "Sunita Patil")
        self.assertTrue(appointment.patient.is_unknown)

    def test_same_person_rebooking_reuses_their_record(self):
        existing = Patient.objects.create(
            full_name="Sunita Patil", mobile="9822011223", sex="F",
            age_years_at_registration=44, privacy_notice_accepted=True,
        )
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:30", "full_name": "Sunita Patil", "mobile": "9822011223",
        })
        self.assertEqual(Appointment.objects.get().patient, existing)
        self.assertEqual(Patient.objects.filter(mobile="9822011223").count(), 1)

    def test_shortened_first_name_still_matches_the_same_person(self):
        existing = Patient.objects.create(
            full_name="Sunita Patil", mobile="9822011223", sex="F",
            age_years_at_registration=44, privacy_notice_accepted=True,
        )
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "12:00", "full_name": "sunita", "mobile": "9822011223",
        })
        self.assertEqual(Appointment.objects.get().patient, existing)

    def test_bad_mobile_is_rejected(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": "11:00", "full_name": "B", "mobile": "12345",
        })
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertContains(resp, "valid 10-digit")


class BookingAbuseTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def _post(self, mobile="9876543210", slot="11:00", **extra):
        payload = {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "slot_time": slot, "full_name": "Ravi", "mobile": mobile,
        }
        payload.update(extra)
        return self.client.post(reverse("site:book"), payload)

    def test_honeypot_silently_drops_the_submission(self):
        resp = self._post(website="http://spam.example")
        self.assertRedirects(resp, reverse("site:book_done"))
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(
            PublicBookingAttempt.objects.get().outcome, PublicBookingAttempt.Outcome.SPAM
        )

    def test_ip_is_rate_limited(self):
        from .throttle import IP_ATTEMPTS_PER_HOUR

        for _ in range(IP_ATTEMPTS_PER_HOUR):
            PublicBookingAttempt.objects.create(
                ip_address="127.0.0.1", outcome=PublicBookingAttempt.Outcome.REJECTED
            )
        resp = self._post()
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertContains(resp, "Too many booking attempts")

    def test_one_mobile_cannot_hold_many_open_appointments(self):
        from .throttle import MOBILE_OPEN_APPOINTMENTS

        patient = Patient.objects.create(
            full_name="Ravi", mobile="9876543210", privacy_notice_deferred=True
        )
        for i in range(MOBILE_OPEN_APPOINTMENTS):
            Appointment.objects.create(
                patient=patient, doctor=self.doctor,
                date=self.tomorrow + timedelta(days=i + 1), slot_time="12:00",
            )
        resp = self._post()
        self.assertContains(resp, "already has upcoming appointments")
        self.assertEqual(Appointment.objects.count(), MOBILE_OPEN_APPOINTMENTS)

    def test_purge_command_drops_only_stale_rows(self):
        fresh = PublicBookingAttempt.objects.create(
            outcome=PublicBookingAttempt.Outcome.BOOKED
        )
        stale = PublicBookingAttempt.objects.create(
            outcome=PublicBookingAttempt.Outcome.BOOKED
        )
        PublicBookingAttempt.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=PublicBookingAttempt.RETENTION_DAYS + 1)
        )
        call_command("purge_booking_attempts", verbosity=0)
        self.assertEqual(list(PublicBookingAttempt.objects.values_list("pk", flat=True)), [fresh.pk])


@AS_DEPLOYED
class PublicHostIsolationTests(TestCase):
    """The whole point of the deployment: manwatkarhospital.in must not be able
    to reach a patient record, even for an authenticated staff user."""

    def setUp(self):
        make_doctor()
        self.staff = User.objects.create_superuser(username="boss", password="pw12345678")

    def test_public_host_serves_the_website(self):
        for name in ("site:home", "site:doctors", "site:services", "site:contact", "site:book"):
            resp = self.client.get(reverse(name), HTTP_HOST=PUBLIC_HOST)
            self.assertEqual(resp.status_code, 200, name)

    def test_public_host_cannot_reach_the_clinical_app(self):
        blocked = [
            "/patients/", "/opd/", "/rx/", "/lab/", "/pharmacy/",
            "/attendance/", "/comms/", "/assist/", "/dashboard/",
            "/admin/", "/login/", "/healthz/",
        ]
        for path in blocked:
            resp = self.client.get(path, HTTP_HOST=PUBLIC_HOST)
            self.assertEqual(resp.status_code, 404, f"{path} leaked with {resp.status_code}")

    def test_signed_in_staff_still_blocked_on_the_public_host(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/patients/", HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 404)

    def test_lan_host_reaches_the_clinical_app(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/dashboard/", HTTP_HOST=LAN_HOST).status_code, 200)
        self.assertEqual(self.client.get("/patients/", HTTP_HOST=LAN_HOST).status_code, 200)

    def test_call_log_stays_private_even_with_telephony_enabled(self):
        # The webhook routes open up, but the page listing callers' numbers
        # must not — it is in the same app and the same namespace.
        with override_settings(VOICE_AGENT_ENABLED=True, TWILIO_AUTH_TOKEN="t"):
            self.client.force_login(self.staff)
            resp = self.client.get(reverse("voice:call_log"), HTTP_HOST=PUBLIC_HOST)
            self.assertEqual(resp.status_code, 404)

    def test_voice_webhook_is_reachable_only_when_telephony_is_enabled(self):
        url = reverse("voice:incoming")
        # Off: not exposed at all.
        resp = self.client.post(url, {"CallSid": "CA1"}, HTTP_HOST=PUBLIC_HOST)
        self.assertEqual(resp.status_code, 404)
        # On: routed through to the view, which then rejects the missing
        # signature itself (403, not 404 — it exists but is unauthenticated).
        with override_settings(VOICE_AGENT_ENABLED=True, TWILIO_AUTH_TOKEN="secret"):
            resp = self.client.post(url, {"CallSid": "CA1"}, HTTP_HOST=PUBLIC_HOST)
            self.assertEqual(resp.status_code, 403)

    def test_staff_login_link_hidden_on_the_public_host_only(self):
        public = self.client.get(reverse("site:home"), HTTP_HOST=PUBLIC_HOST)
        lan = self.client.get(reverse("site:home"), HTTP_HOST=LAN_HOST)
        self.assertNotContains(public, "Staff sign in")
        self.assertContains(lan, "Staff sign in")


class TemplateHygieneTests(TestCase):
    """Django's {# #} comment cannot span lines — a multi-line one is not a
    comment at all, it renders to the visitor as literal text. This shipped
    once on the booking page; the scan is cheap insurance against a repeat."""

    def test_no_template_has_a_multi_line_hash_comment(self):
        import re
        from pathlib import Path

        from django.conf import settings

        offenders = []
        roots = [Path(d) for d in settings.TEMPLATES[0]["DIRS"]]
        for root in roots:
            for path in root.rglob("*.html"):
                text = path.read_text()
                for match in re.finditer(r"\{#(.*?)#\}", text, re.S):
                    if "\n" in match.group(0):
                        line = text[: match.start()].count("\n") + 1
                        offenders.append(f"{path.name}:{line}")
        self.assertEqual(
            offenders, [],
            f"Multi-line {{# #}} renders as visible text — use {{% comment %}}: {offenders}",
        )

    def test_public_pages_render_no_raw_template_syntax(self):
        make_doctor()
        for name in ("site:home", "site:doctors", "site:services", "site:contact", "site:book"):
            body = self.client.get(reverse(name)).content.decode()
            self.assertNotIn("{#", body, name)
            self.assertNotIn("{%", body, name)


class DoctorPublishingTests(TestCase):
    def test_online_booking_requires_a_public_profile(self):
        doctor = make_doctor(public=False, online=False)
        doctor.accepts_online_booking = True
        with self.assertRaises(ValidationError):
            doctor.full_clean()
