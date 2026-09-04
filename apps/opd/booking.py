"""Shared appointment-booking service.

Both self-service front doors — the AI phone receptionist (apps.voice) and the
public website (apps.site) — book through this module rather than touching
Appointment directly. Keeping one path means the race protection and the
"never offer a slot we won't honour" rule are written once and tested once.

Staff booking goes through apps.opd.views/services instead; that path is
authenticated and may legitimately override the public slot grid.
"""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.opd.models import Appointment
from apps.patients.models import Patient

# Default OPD windows for slot generation.
MORNING = (time(10, 0), time(13, 0))
EVENING = (time(17, 0), time(20, 0))
WORKING_WINDOWS = [MORNING, EVENING]

# PLAN.md: "OPD closed Tuesday evenings". Monday is weekday() == 0, so Tuesday
# is 1. Without this the website would sell Tuesday-evening slots and patients
# would arrive at a closed OPD.
TUESDAY = 1
# The hospital confirmed Sunday OPD runs, so OPD_SUNDAY_OPEN defaults on and
# Sunday gets the normal weekday windows. Kept as a switch so a future closure
# needs a config change, not a deploy.
SUNDAY = 6


def windows_for(on_date):
    """The OPD windows actually running on a given date."""
    weekday = on_date.weekday()
    if weekday == SUNDAY and not settings.OPD_SUNDAY_OPEN:
        return []
    if weekday == TUESDAY:
        return [MORNING]
    return WORKING_WINDOWS

# How far ahead self-service booking may reach. Beyond this the caller is asked
# to phone the hospital, so the doctor's leave/OT calendar stays authoritative.
MAX_ADVANCE_DAYS = 30


def find_doctors(public_only=False):
    qs = DoctorProfile.objects.order_by("display_name")
    if public_only:
        qs = qs.filter(show_on_website=True)
    return {
        "doctors": [
            {
                "name": d.display_name,
                "specialty": d.specialty or "General",
                "fee": str(d.consult_fee),
            }
            for d in qs
        ]
    }


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
        hit = qs.filter(display_name__icontains=token).first() or qs.filter(
            specialty__icontains=token
        ).first()
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
    """(ok, error) — self-service may book today through MAX_ADVANCE_DAYS out."""
    if on_date is None:
        return False, "Please give a valid date, today or later."
    today = timezone.localdate()
    if on_date < today:
        return False, "Please give a valid date, today or later."
    if on_date > today + timedelta(days=MAX_ADVANCE_DAYS):
        return False, (
            f"Online booking is open {MAX_ADVANCE_DAYS} days ahead. "
            "For a later date please call the hospital."
        )
    return True, ""


def available_slots(doctor_name, date_str, limit=6):
    doctor = resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = parse_date(date_str)
    ok, error = _bookable_date(on_date)
    if not ok:
        return {"ok": False, "error": error}

    taken = {}
    for slot in Appointment.objects.filter(
        doctor=doctor,
        date=on_date,
        status__in=[Appointment.Status.BOOKED, Appointment.Status.CHECKED_IN],
    ).values_list("slot_time", flat=True):
        label = slot.strftime("%H:%M")
        taken[label] = taken.get(label, 0) + 1

    now = timezone.localtime()
    free = []
    step = timedelta(minutes=settings.OPD_DEFAULT_SLOT_MINUTES)
    for start, end in windows_for(on_date):
        cursor = datetime.combine(on_date, start)
        end_dt = datetime.combine(on_date, end)
        while cursor < end_dt:
            label = cursor.strftime("%H:%M")
            is_future = on_date > now.date() or cursor.time() > now.time()
            if is_future and taken.get(label, 0) < settings.OPD_SLOT_CAPACITY:
                free.append(label)
            cursor += step
    return {
        "ok": True,
        "doctor": doctor.display_name,
        "date": on_date.isoformat(),
        "slots": free[:limit],
    }


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
        # Exact, or one name contained in the other ("Sunita" vs "Sunita Patil"),
        # which covers how people shorten their own names on a form.
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


def book_appointment(patient_name, mobile, doctor_name, date_str, time_str,
                     source="AI phone agent", reason=""):
    doctor = resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = parse_date(date_str)
    ok, error = _bookable_date(on_date)
    if not ok:
        return {"ok": False, "error": error}
    try:
        slot_time = datetime.strptime((time_str or "").strip(), "%H:%M").time()
    except ValueError:
        return {"ok": False, "error": "Time must be HH:MM (24-hour)."}

    mobile_digits = normalise_mobile(mobile)
    if len(mobile_digits) != 10:
        return {"ok": False, "error": "Need a valid 10-digit mobile number."}

    slot_label = slot_time.strftime("%H:%M")
    # Serialize per-doctor so two concurrent bookings can't take the same slot,
    # and only accept a slot that available_slots would actually offer (future,
    # within OPD hours, not already taken).
    with transaction.atomic():
        DoctorProfile.objects.select_for_update().get(pk=doctor.pk)
        avail = available_slots(doctor_name, date_str, limit=10000)
        if not avail.get("ok") or slot_label not in avail["slots"]:
            return {"ok": False, "error": "That time is not available. Offer one of the free slots."}
        patient = get_or_create_patient(patient_name, mobile_digits)
        note = f"Booked by {source}"
        if reason:
            note = f"{note} · {reason}"[:240]
        appointment = Appointment.objects.create(
            patient=patient,
            doctor=doctor,
            date=on_date,
            slot_time=slot_time,
            duration_minutes=settings.OPD_DEFAULT_SLOT_MINUTES,
            notes=note,
        )
    queue_confirmation(appointment)
    # Keep every value JSON-serialisable: this dict is handed straight to
    # json.dumps() as a tool_result for the phone agent.
    return {
        "ok": True,
        "appointment_id": str(appointment.id),
        "patient_id": str(patient.id),
        "confirmation": (
            f"Booked for {patient.full_name} with {doctor.display_name} on "
            f"{on_date:%d %b} at {slot_time:%H:%M}."
        ),
    }


def queue_confirmation(appointment):
    """Best-effort confirmation message. A messaging outage must never lose an
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
            body=(
                f"{hospital.name}: appointment confirmed with "
                f"{appointment.doctor.display_name} on {appointment.date:%d-%b-%Y} at "
                f"{appointment.slot_time:%H:%M}."
            ),
            purpose=OutboundMessage.Purpose.APPOINTMENT,
            reference=f"appt:{appointment.id}",
            scheduled_for=appointment.date,
        )
    except Exception:
        pass  # confirmation is best-effort; the booking itself stands
