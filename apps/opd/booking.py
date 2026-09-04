"""Shared appointment-booking service.

Both self-service front doors — the AI phone receptionist (apps.voice) and the
public website (apps.site) — book through this module rather than touching
Appointment directly, so the OPD calendar is written once and tested once.

Staff booking goes through apps.opd.views/forms instead; that path is
authenticated and may legitimately override anything here.

The OPD does not run numbered appointment slots. Patients are booked into a
SESSION and seen in token order on arrival, which is how the desk actually
works — so this module offers sessions, never a grid of times, and never
refuses a booking because a "slot" is taken.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.opd.models import Appointment
from apps.patients.models import Patient


class Session:
    """One OPD sitting. Unlimited capacity — token order, not clock slots."""

    def __init__(self, key, start, end, label):
        self.key, self.start, self.end, self.label = key, start, end, label

    @property
    def duration_minutes(self):
        return int(
            (datetime.combine(datetime.min, self.end)
             - datetime.combine(datetime.min, self.start)).total_seconds() // 60
        )

    def human(self):
        return f"{self.start:%H:%M}–{self.end:%H:%M}"

    def as_dict(self):
        return {"key": self.key, "label": self.label, "start": f"{self.start:%H:%M}",
                "end": f"{self.end:%H:%M}", "time": self.human()}


MORNING = Session("morning", time(10, 0), time(15, 0), "Morning OPD")
EVENING = Session("evening", time(18, 0), time(22, 0), "Evening OPD")
SESSIONS = {s.key: s for s in (MORNING, EVENING)}

# weekday(): Mon=0 … Sat=5, Sun=6.
TUESDAY, SATURDAY = 1, 5
# Evening OPD does not run on these days. Mornings run every day, Sunday
# included. Casualty is open 24/7 and is never booked through this module.
EVENING_CLOSED = {TUESDAY, SATURDAY}

# How far ahead self-service booking may reach. Beyond this the caller is asked
# to phone the hospital, so the doctor's leave/OT calendar stays authoritative.
MAX_ADVANCE_DAYS = 30


def sessions_for(on_date):
    """The OPD sittings that actually run on a given date."""
    running = [MORNING]
    if on_date.weekday() not in EVENING_CLOSED:
        running.append(EVENING)
    return running


# Marathi weekday names, for the bilingual OPD board on the public site.
WEEKDAYS = [
    ("Monday", "सोमवार"), ("Tuesday", "मंगळवार"), ("Wednesday", "बुधवार"),
    ("Thursday", "गुरुवार"), ("Friday", "शुक्रवार"), ("Saturday", "शनिवार"),
    ("Sunday", "रविवार"),
]


def weekly_timetable():
    """The OPD board, generated from the same constants the booking engine uses.

    The published hours and the hours the system will actually accept are the
    same data, so the website cannot advertise a sitting that booking would
    refuse. Change EVENING_CLOSED and the board changes with it.
    """
    rows = []
    for index, (english, marathi) in enumerate(WEEKDAYS):
        rows.append({
            "en": english, "mr": marathi,
            "morning": True,
            "evening": index not in EVENING_CLOSED,
        })
    return rows


def find_doctors(public_only=False):
    qs = DoctorProfile.objects.order_by("display_name")
    if public_only:
        qs = qs.filter(show_on_website=True)
    return {"doctors": [{"name": d.display_name,
                         "specialty": d.specialty or "General",
                         "fee": str(d.consult_fee)} for d in qs]}


def resolve_doctor(name):
    """Match a doctor the way a caller names one: exact, then any word of the
    name, then specialty ("the gynec doctor")."""
    name = (name or "").strip()
    if not name:
        return None
    qs = DoctorProfile.objects.all()
    exact = qs.filter(display_name__iexact=name).first()
    if exact:
        return exact
    for token in name.split():
        if len(token) < 3:
            continue
        hit = (qs.filter(display_name__icontains=token).first()
               or qs.filter(specialty__icontains=token).first())
        if hit:
            return hit
    return None


def parse_date(date_str):
    date_str = (date_str or "").strip().lower()
    today = timezone.localdate()
    if date_str in ("", "today"):
        return today
    if date_str == "tomorrow":
        return today + timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            continue
    return None


def _bookable_date(on_date):
    if on_date is None:
        return False, "Please give a valid date, today or later."
    today = timezone.localdate()
    if on_date < today:
        return False, "Please give a valid date, today or later."
    if on_date > today + timedelta(days=MAX_ADVANCE_DAYS):
        return False, (f"Online booking is open {MAX_ADVANCE_DAYS} days ahead. "
                       "For a later date please call the hospital.")
    return True, ""


def available_sessions(doctor_name, date_str):
    """Sittings a patient can still book. Capacity is never a reason to refuse —
    only the calendar, and a session that has already ended today."""
    doctor = resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = parse_date(date_str)
    ok, error = _bookable_date(on_date)
    if not ok:
        return {"ok": False, "error": error}

    now = timezone.localtime()
    running = []
    for session in sessions_for(on_date):
        if on_date == now.date() and session.end <= now.time():
            continue  # that sitting is over for today
        running.append(session.as_dict())
    return {"ok": True, "doctor": doctor.display_name,
            "date": on_date.isoformat(), "sessions": running}


def normalise_mobile(mobile):
    return "".join(c for c in (mobile or "") if c.isdigit())[-10:]


def find_patient(mobile):
    mobile = normalise_mobile(mobile)
    if len(mobile) != 10:
        return {"found": False}
    patient = Patient.objects.filter(mobile=mobile, is_active=True).order_by("-created_at").first()
    if patient is None:
        return {"found": False}
    return {"found": True, "name": patient.full_name, "uhid": patient.uhid}


def get_or_create_patient(name, mobile):
    """Reuse the caller's existing record, but only when the name they gave
    actually matches it.

    One mobile number per household is normal here — a wife books on her
    husband's number, a son books for his mother. Matching on the number alone
    would file her appointment on his chart, and the consultation would be
    documented against the wrong patient. So a mismatched name creates a fresh
    provisional record instead. A duplicate is a nuisance reception can merge;
    a wrong chart is a clinical safety incident.
    """
    from apps.patients.services import normalize_name

    mobile = normalise_mobile(mobile)
    given = normalize_name(name)
    for existing in Patient.objects.filter(mobile=mobile, is_active=True).order_by("-created_at"):
        if not given:
            break
        held = existing.name_normalized or normalize_name(existing.full_name)
        if given == held or (len(given) >= 4 and (given in held or held in given)):
            return existing

    # Provisional record — flagged unknown; reception completes identity, sex,
    # age and DPDP consent on arrival. sex is a valid choice (not blank).
    return Patient.objects.create(
        full_name=(name or "").strip() or "Phone booking",
        mobile=mobile,
        sex=Patient.Sex.OTHER,
        is_unknown=True,
        privacy_notice_deferred=True,
        privacy_notice_deferred_reason="Self-service booking — consent captured at reception",
    )


def book_appointment(patient_name, mobile, doctor_name, date_str, session_key,
                     source="AI phone agent", reason=""):
    """Book into a session. Never refuses for capacity — the OPD is walk-in
    within its sitting, so the only refusals are calendar or data errors."""
    doctor = resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = parse_date(date_str)
    ok, error = _bookable_date(on_date)
    if not ok:
        return {"ok": False, "error": error}

    session = SESSIONS.get((session_key or "").strip().lower())
    if session is None:
        return {"ok": False, "error": "Choose 'morning' or 'evening'."}

    available = available_sessions(doctor_name, date_str)
    if not available.get("ok"):
        return {"ok": False, "error": available.get("error", "Not available.")}
    if session.key not in {s["key"] for s in available["sessions"]}:
        return {"ok": False, "error":
                f"There is no {session.label.lower()} that day. Offer one of the sittings that runs."}

    mobile_digits = normalise_mobile(mobile)
    if len(mobile_digits) != 10:
        return {"ok": False, "error": "Need a valid 10-digit mobile number."}

    note = f"Booked by {source} · {session.label}"
    if reason:
        note = f"{note} · {reason}"
    with transaction.atomic():
        patient = get_or_create_patient(patient_name, mobile_digits)
        appointment = Appointment.objects.create(
            patient=patient, doctor=doctor, date=on_date,
            slot_time=session.start, duration_minutes=session.duration_minutes,
            notes=note[:240],
        )
    queue_confirmation(appointment, session)
    return {
        "ok": True,
        "appointment_id": str(appointment.id),
        "patient_id": str(patient.id),
        "session": session.as_dict(),
        "confirmation": (f"Booked for {patient.full_name} with {doctor.display_name} on "
                         f"{on_date:%d %b}, {session.label.lower()} ({session.human()}). "
                         "Come any time during the sitting."),
    }


def queue_confirmation(appointment, session):
    """Best-effort confirmation. A messaging outage must never lose an
    appointment the patient believes is booked, so failures are swallowed."""
    try:
        from apps.comms import services as comms_services
        from apps.comms.models import OutboundMessage
        from apps.core.models import HospitalProfile

        hospital = HospitalProfile.get_solo()
        comms_services.queue_message(
            patient=appointment.patient,
            channel=settings.OPD_REMINDER_CHANNEL,
            to_number=appointment.patient.mobile,
            body=(f"{hospital.name}: appointment confirmed with "
                  f"{appointment.doctor.display_name} on {appointment.date:%d-%b-%Y}, "
                  f"{session.label.lower()} {session.human()}. Come any time during the sitting."),
            purpose=OutboundMessage.Purpose.APPOINTMENT,
            reference=f"appt:{appointment.id}",
            scheduled_for=appointment.date,
        )
    except Exception:
        pass  # confirmation is best-effort; the booking itself stands
