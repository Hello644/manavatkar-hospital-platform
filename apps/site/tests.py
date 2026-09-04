from datetime import timedelta
from decimal import Decimal

from django.conf import settings
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


def next_full_opd_day():
    """Next date running BOTH sittings. Tests must not depend on what day they
    are run — evening OPD is closed Tuesday and Saturday, so a bare
    "tomorrow" silently breaks the suite twice a week."""
    from apps.opd.booking import EVENING_CLOSED

    d = timezone.localdate() + timedelta(days=1)
    while d.weekday() in EVENING_CLOSED:
        d += timedelta(days=1)
    return d


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
        self.tomorrow = next_full_opd_day()

    def _slots(self):
        resp = self.client.get(
            reverse("site:book"), {"doctor": self.doctor.pk, "date": self.tomorrow.isoformat()}
        )
        return resp

    def test_picking_a_doctor_and_date_shows_the_sittings(self):
        resp = self._slots()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Morning OPD")
        self.assertContains(resp, "10:00–15:00")

    def test_booking_creates_appointment_and_provisional_patient(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": "morning", "full_name": "Ravi Kumar",
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
            "session": "morning", "full_name": "Ravi Kumar", "mobile": "9876543210",
        })
        # First view consumes it; a refresh must not re-print the details.
        self.client.get(reverse("site:book_done"))
        resp = self.client.get(reverse("site:book_done"))
        self.assertNotContains(resp, "Ravi Kumar")

    def test_unknown_sitting_is_refused(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": "afternoon", "full_name": "Ravi", "mobile": "9876543210",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_a_busy_sitting_never_blocks_a_new_booking(self):
        """Unlimited capacity — a full morning must still accept one more."""
        patient = Patient.objects.create(
            full_name="A", mobile="9000000000", privacy_notice_deferred=True
        )
        Appointment.objects.create(
            patient=patient, doctor=self.doctor, date=self.tomorrow, slot_time="10:00"
        )
        self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": "morning", "full_name": "Bhaskar", "mobile": "9876543210",
        })
        self.assertEqual(Appointment.objects.count(), 2)

    def test_doctor_not_opted_into_online_booking_cannot_be_booked(self):
        offline = make_doctor("Dr. Offline Only", "ENT", public=True, online=False)
        self.client.post(reverse("site:book"), {
            "doctor": offline.pk, "date": self.tomorrow.isoformat(),
            "session": "morning", "full_name": "Bhaskar", "mobile": "9876543210",
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
            "session": "morning", "full_name": "Sunita Patil", "mobile": "9822011223",
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
            "session": "morning", "full_name": "Sunita Patil", "mobile": "9822011223",
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
            "session": "evening", "full_name": "sunita", "mobile": "9822011223",
        })
        self.assertEqual(Appointment.objects.get().patient, existing)

    def test_bad_mobile_is_rejected(self):
        resp = self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": "morning", "full_name": "B", "mobile": "12345",
        })
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertContains(resp, "valid 10-digit")


class OpdCalendarTests(TestCase):
    """The OPD runs two sittings, and evening OPD does not run on Tuesday or
    Saturday. Selling a sitting the hospital does not hold sends a patient to a
    dark building, so the self-service path has to know the calendar."""

    def setUp(self):
        self.doctor = make_doctor()

    def _next(self, weekday):
        d = timezone.localdate() + timedelta(days=1)
        while d.weekday() != weekday:
            d += timedelta(days=1)
        return d

    def _keys(self, on_date):
        from apps.opd import booking

        r = booking.available_sessions(self.doctor.display_name, on_date.isoformat())
        return [s["key"] for s in r["sessions"]] if r.get("ok") else []

    def test_normal_day_runs_both_sittings(self):
        self.assertEqual(self._keys(self._next(2)), ["morning", "evening"])  # Wednesday

    def test_sunday_runs_both_sittings(self):
        self.assertEqual(self._keys(self._next(6)), ["morning", "evening"])

    def test_tuesday_has_no_evening(self):
        self.assertEqual(self._keys(self._next(1)), ["morning"])

    def test_saturday_has_no_evening(self):
        self.assertEqual(self._keys(self._next(5)), ["morning"])

    def test_booking_a_closed_evening_is_refused(self):
        for weekday in (1, 5):  # Tuesday, Saturday
            Appointment.objects.all().delete()
            resp = self.client.post(reverse("site:book"), {
                "doctor": self.doctor.pk, "date": self._next(weekday).isoformat(),
                "session": "evening", "full_name": "Ravi", "mobile": "9876543210",
            })
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(Appointment.objects.count(), 0, f"weekday {weekday} sold an evening")

    def test_sittings_have_the_right_hours(self):
        from apps.opd import booking

        self.assertEqual(booking.MORNING.human(), "10:00–15:00")
        self.assertEqual(booking.EVENING.human(), "18:00–22:00")


class UnlimitedCapacityTests(TestCase):
    """No numbered slots and no cap: the OPD is walk-in within a sitting."""

    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = next_full_opd_day()

    def test_many_patients_can_book_the_same_sitting(self):
        from apps.opd import booking

        for i in range(25):
            r = booking.book_appointment(
                f"Patient {i}", f"98765{i:05d}", self.doctor.display_name,
                self.tomorrow.isoformat(), "morning", source="website",
            )
            self.assertTrue(r.get("ok"), r)
        self.assertEqual(Appointment.objects.count(), 25)

    def test_booking_records_the_sitting_window(self):
        from apps.opd import booking

        booking.book_appointment("A", "9876543210", self.doctor.display_name,
                                 self.tomorrow.isoformat(), "evening", source="website")
        appt = Appointment.objects.get()
        self.assertEqual(appt.slot_time.strftime("%H:%M"), "18:00")
        self.assertEqual(appt.duration_minutes, 240)
        self.assertIn("Evening OPD", appt.notes)


class BookingAbuseTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = next_full_opd_day()

    def _post(self, mobile="9876543210", session="morning", **extra):
        payload = {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": session, "full_name": "Ravi", "mobile": mobile,
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
        from .throttle import REFUSED

        resp = self._post()
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertContains(resp, REFUSED)

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
        from .throttle import REFUSED

        resp = self._post()
        self.assertContains(resp, REFUSED)
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


class OpdBoardTests(TestCase):
    """The published board is safety-critical: someone reads it and decides
    when to travel to the hospital. It is generated from the booking engine's
    own constants so it cannot drift from what booking will accept."""

    def setUp(self):
        make_doctor()

    def _rows(self):
        """The board's data rows, keyed by day. Scoped to <tbody> so trailing
        prose that happens to mention a weekday cannot be mistaken for a row."""
        import re

        body = self.client.get(reverse("site:home")).content.decode()
        tbody = re.search(r"<tbody>(.*?)</tbody>", body, re.S).group(1)
        rows = {}
        for chunk in re.findall(r"<tr>(.*?)</tr>", tbody, re.S):
            day = re.search(r'class="day">([A-Za-z]+)', chunk)
            if day:
                rows[day.group(1)] = chunk
        return rows

    def test_board_states_closed_evenings_in_words(self):
        """It used to strike through the normal time, and the 1px line vanished
        at reading size — you would read 18:00-22:00 and travel on a Tuesday."""
        rows = self._rows()
        for day in ("Tuesday", "Saturday"):
            self.assertIn("Closed", rows[day], f"{day} evening does not say Closed")
            self.assertIn("बंद", rows[day])
            self.assertNotIn("18:00–22:00", rows[day],
                             f"{day} still shows an evening time a patient could act on")

    def test_board_shows_open_evenings_as_times(self):
        rows = self._rows()
        for day in ("Monday", "Wednesday", "Thursday", "Friday", "Sunday"):
            self.assertIn("18:00–22:00", rows[day])
            self.assertNotIn("Closed", rows[day])

    def test_board_lists_every_day_once(self):
        self.assertEqual(len(self._rows()), 7)

    def test_board_matches_what_booking_will_accept(self):
        """Every day the board calls open must actually be bookable, and every
        day it calls closed must be refused."""
        from datetime import timedelta

        from apps.opd import booking

        board = {r["en"]: r["evening"] for r in booking.weekly_timetable()}
        day = timezone.localdate() + timedelta(days=1)
        for _ in range(7):
            name = booking.WEEKDAYS[day.weekday()][0]
            offered = {s["key"] for s in
                       booking.available_sessions("Madhu", day.isoformat())["sessions"]}
            self.assertEqual(
                "evening" in offered, board[name],
                f"board and booking disagree about {name} evening",
            )
            day += timedelta(days=1)


class StaticAssetTests(TestCase):
    """The stylesheet URL must change when the file does.

    A browser once cached a failed response for /static/css/site.css and then
    stopped asking for it: the server logged GET / 200 with no stylesheet
    request at all, and the site rendered as unstyled black text. In production
    WhiteNoise's manifest hashes the filename; this covers DEBUG.
    """

    @override_settings(DEBUG=True)
    def test_stylesheet_url_is_versioned_in_debug(self):
        import re

        body = self.client.get(reverse("site:home")).content.decode()
        href = re.search(r'<link rel="stylesheet" href="([^"]+)"', body).group(1)
        self.assertRegex(href, r"^/static/css/site\.css\?v=\d+$", f"not cache-busted: {href}")

    @override_settings(DEBUG=False)
    def test_stylesheet_url_is_plain_when_not_debug(self):
        """Production hashes the filename via the manifest, so no query string."""
        body = self.client.get(reverse("site:home"), HTTP_HOST="testserver").content.decode()
        self.assertIn("/static/css/site.css", body)
        self.assertNotIn("site.css?v=", body)

    def test_page_opts_out_of_forced_dark_mode(self):
        css = (settings.BASE_DIR / "static" / "css" / "site.css").read_text()
        self.assertIn("color-scheme: only light", css)


class StaticExportTests(TestCase):
    """The export is published to a CDN, so anything it contains is public
    forever. These guard what may and may not travel."""

    def setUp(self):
        make_doctor()
        Service.objects.create(name="General Medicine", name_marathi="सामान्य वैद्यक")

    def _export(self):
        import tempfile
        from pathlib import Path

        out = Path(tempfile.mkdtemp()) / "dist"
        call_command("export_public_site", out=str(out), verbosity=0)
        return out

    def test_export_contains_no_route_into_the_clinical_system(self):
        out = self._export()
        blob = "".join(p.read_text() for p in out.rglob("*") if p.is_file())
        for needle in ("/login/", "/dashboard/", "/patients/", "/admin/",
                       "/attendance/", "Staff sign in", "csrfmiddlewaretoken"):
            self.assertNotIn(needle, blob, f"static export would publish {needle}")

    def test_export_shows_the_telephone_instead_of_a_dead_form(self):
        book = (self._export() / "book" / "index.html").read_text()
        self.assertIn("Book by telephone", book)
        self.assertNotIn('<form method="post"', book)

    def test_export_still_carries_the_opd_board(self):
        home = (self._export() / "index.html").read_text()
        for day in ("Monday", "सोमवार", "Tuesday", "Closed", "बंद"):
            self.assertIn(day, home)
        self.assertIn("10:00–15:00", home)

    def test_export_writes_every_page_and_the_stylesheet(self):
        out = self._export()
        for rel in ("index.html", "doctors/index.html", "services/index.html",
                    "contact/index.html", "book/index.html", "robots.txt",
                    "sitemap.xml", "static/css/site.css", "vercel.json"):
            self.assertTrue((out / rel).exists(), f"missing {rel}")


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


@AS_DEPLOYED
class HostSpoofingTests(TestCase):
    """Regression tests for a confirmed breach: `Host: manwatkarhospital.in.`
    (the legal fully-qualified form, which curl and browsers accept) did not
    match PUBLIC_SITE_HOSTS, so the request fell through as "LAN" and
    /patients/ answered over the internet. Django strips the trailing dot when
    checking ALLOWED_HOSTS, so the request got that far quite happily."""

    VARIANTS = [
        "manwatkarhospital.in",
        "manwatkarhospital.in.",              # the breach
        "MANWATKARHOSPITAL.IN",
        "MaNwAtKaRhOsPiTaL.In.",
        "manwatkarhospital.in:8000",
        "manwatkarhospital.in.:8000",
        "www.manwatkarhospital.in",
        "www.manwatkarhospital.in.",
    ]

    def setUp(self):
        make_doctor()
        self.staff = User.objects.create_superuser(username="boss2", password="pw12345678")

    def test_every_spelling_of_the_public_host_is_isolated(self):
        self.client.force_login(self.staff)
        for host in self.VARIANTS:
            resp = self.client.get("/patients/", HTTP_HOST=host)
            self.assertEqual(resp.status_code, 404, f"{host} reached the clinical app")

    def test_every_spelling_still_serves_the_public_site(self):
        for host in self.VARIANTS:
            resp = self.client.get(reverse("site:home"), HTTP_HOST=host)
            self.assertEqual(resp.status_code, 200, f"{host} lost the public site")

    def test_x_forwarded_host_cannot_downgrade_to_lan(self):
        self.client.force_login(self.staff)
        resp = self.client.get(
            "/patients/", HTTP_HOST="manwatkarhospital.in",
            HTTP_X_FORWARDED_HOST="hms.hospital.lan",
        )
        self.assertEqual(resp.status_code, 404)

    def test_append_slash_does_not_confirm_internal_paths(self):
        """/patients returned 301 -> /patients/ while /nonsense returned 404,
        handing the internet a directory of our internal apps."""
        for path in ("/patients", "/opd", "/admin", "/attendance"):
            resp = self.client.get(path, HTTP_HOST=PUBLIC_HOST)
            self.assertEqual(resp.status_code, 404, f"{path} leaked via APPEND_SLASH")

    def test_append_slash_still_works_for_public_pages_and_on_lan(self):
        self.assertEqual(
            self.client.get("/doctors", HTTP_HOST=PUBLIC_HOST).status_code, 301
        )
        self.assertEqual(self.client.get("/patients", HTTP_HOST=LAN_HOST).status_code, 301)


class BookingOracleTests(TestCase):
    """The booking form must not answer "is this number a patient here?" for an
    anonymous stranger. Every refusal reads identically."""

    def setUp(self):
        self.doctor = make_doctor()
        self.tomorrow = next_full_opd_day()

    def _post(self, mobile):
        return self.client.post(reverse("site:book"), {
            "doctor": self.doctor.pk, "date": self.tomorrow.isoformat(),
            "session": "morning", "full_name": "Ravi", "mobile": mobile,
        })

    def test_known_and_unknown_numbers_get_the_same_refusal(self):
        from .throttle import MOBILE_OPEN_APPOINTMENTS, REFUSED

        patient = Patient.objects.create(
            full_name="Sunita", mobile="9822011223", privacy_notice_deferred=True
        )
        for i in range(MOBILE_OPEN_APPOINTMENTS):
            Appointment.objects.create(
                patient=patient, doctor=self.doctor,
                date=self.tomorrow + timedelta(days=i + 1), slot_time="12:00",
            )
        # A number with appointments is refused...
        known = self._post("9822011223")
        self.assertContains(known, REFUSED)
        # ...and nothing in the response distinguishes it from any other refusal.
        self.assertNotContains(known, "already has")
        self.assertNotContains(known, "upcoming")

    def test_staff_still_see_the_real_reason_in_the_audit_log(self):
        from .throttle import IP_ATTEMPTS_PER_HOUR

        for _ in range(IP_ATTEMPTS_PER_HOUR):
            PublicBookingAttempt.objects.create(
                ip_address="127.0.0.1", outcome=PublicBookingAttempt.Outcome.REJECTED
            )
        self._post("9876543210")
        latest = PublicBookingAttempt.objects.first()
        self.assertEqual(latest.outcome, PublicBookingAttempt.Outcome.RATE_LIMITED)
        self.assertIn("ip hourly limit", latest.detail)


class DoctorPublishingTests(TestCase):
    def test_online_booking_requires_a_public_profile(self):
        doctor = make_doctor(public=False, online=False)
        doctor.accepts_online_booking = True
        with self.assertRaises(ValidationError):
            doctor.full_clean()
