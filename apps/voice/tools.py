"""Booking tools exposed to the voice agent. These are the ONLY way the agent
touches the database — plain Django, fully testable without the LLM."""

from datetime import datetime, time, timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.opd.models import Appointment
from apps.patients.models import Patient

# Default OPD windows for slot generation (Tue evening closed per the plan).
WORKING_WINDOWS = [(time(10, 0), time(13, 0)), (time(17, 0), time(20, 0))]


def find_doctors():
    docs = []
    for d in DoctorProfile.objects.order_by("display_name"):
        docs.append({
            "name": d.display_name,
            "specialty": d.specialty or "General",
            "fee": str(d.consult_fee),
        })
    return {"doctors": docs}


def _resolve_doctor(name):
    name = (name or "").strip()
    if not name:
        return None
    qs = DoctorProfile.objects.all()
    exact = qs.filter(display_name__iexact=name).first()
    if exact:
        return exact
    # Loose match on any word (callers say "Doctor Madhu", "gynec", etc.)
    for token in name.split():
        if len(token) < 3:
            continue
        hit = qs.filter(display_name__icontains=token).first() or qs.filter(
            specialty__icontains=token
        ).first()
        if hit:
            return hit
    return None


def _parse_date(date_str):
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


def available_slots(doctor_name, date_str, limit=6):
    doctor = _resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = _parse_date(date_str)
    if on_date is None or on_date < timezone.localdate():
        return {"ok": False, "error": "Please give a valid date, today or later."}

    taken = {}
    for slot in Appointment.objects.filter(
        doctor=doctor, date=on_date,
        status__in=[Appointment.Status.BOOKED, Appointment.Status.CHECKED_IN],
    ).values_list("slot_time", flat=True):
        taken[slot.strftime("%H:%M")] = taken.get(slot.strftime("%H:%M"), 0) + 1

    now = timezone.localtime()
    free = []
    step = timedelta(minutes=settings.OPD_DEFAULT_SLOT_MINUTES)
    for start, end in WORKING_WINDOWS:
        cursor = datetime.combine(on_date, start)
        end_dt = datetime.combine(on_date, end)
        while cursor < end_dt:
            label = cursor.strftime("%H:%M")
            is_future = on_date > now.date() or cursor.time() > now.time()
            if is_future and taken.get(label, 0) < settings.OPD_SLOT_CAPACITY:
                free.append(label)
            cursor += step
    return {
        "ok": True, "doctor": doctor.display_name, "date": on_date.isoformat(),
        "slots": free[:limit],
    }


def find_patient(mobile):
    mobile = "".join(c for c in (mobile or "") if c.isdigit())[-10:]
    if len(mobile) != 10:
        return {"found": False}
    patient = Patient.objects.filter(mobile=mobile, is_active=True).order_by("-created_at").first()
    if patient is None:
        return {"found": False}
    return {"found": True, "name": patient.full_name, "uhid": patient.uhid}


def _get_or_create_patient(name, mobile):
    mobile = "".join(c for c in (mobile or "") if c.isdigit())[-10:]
    existing = Patient.objects.filter(mobile=mobile, is_active=True).order_by("-created_at").first()
    if existing:
        return existing
    # Provisional record — reception completes DPDP consent + age on arrival.
    return Patient.objects.create(
        full_name=name.strip() or "Phone booking",
        mobile=mobile,
        privacy_notice_deferred=True,
        privacy_notice_deferred_reason="Phone booking — consent captured at reception",
    )


def book_appointment(patient_name, mobile, doctor_name, date_str, time_str):
    doctor = _resolve_doctor(doctor_name)
    if doctor is None:
        return {"ok": False, "error": f"No doctor matching '{doctor_name}'."}
    on_date = _parse_date(date_str)
    if on_date is None or on_date < timezone.localdate():
        return {"ok": False, "error": "Invalid date."}
    try:
        slot_time = datetime.strptime((time_str or "").strip(), "%H:%M").time()
    except ValueError:
        return {"ok": False, "error": "Time must be HH:MM (24-hour)."}

    clashes = Appointment.objects.filter(
        doctor=doctor, date=on_date, slot_time=slot_time,
        status__in=[Appointment.Status.BOOKED, Appointment.Status.CHECKED_IN],
    ).count()
    if clashes >= settings.OPD_SLOT_CAPACITY:
        return {"ok": False, "error": "That slot is taken. Offer another time."}

    mobile_digits = "".join(c for c in (mobile or "") if c.isdigit())[-10:]
    if len(mobile_digits) != 10:
        return {"ok": False, "error": "Need a valid 10-digit mobile number."}

    patient = _get_or_create_patient(patient_name, mobile_digits)
    appointment = Appointment.objects.create(
        patient=patient, doctor=doctor, date=on_date, slot_time=slot_time,
        duration_minutes=settings.OPD_DEFAULT_SLOT_MINUTES,
        notes="Booked by AI phone agent",
    )
    _queue_confirmation(appointment)
    return {
        "ok": True,
        "appointment_id": str(appointment.id),
        "patient_id": str(patient.id),
        "confirmation": (
            f"Booked for {patient.full_name} with {doctor.display_name} on "
            f"{on_date:%d %b} at {slot_time:%H:%M}."
        ),
    }


def _queue_confirmation(appointment):
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


# ----------------------------------------------------------- agent tool surface

TOOL_SCHEMAS = [
    {
        "name": "find_doctors",
        "description": "List the hospital's doctors, their specialties and consult fees.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "available_slots",
        "description": "Free appointment times for a doctor on a date. Use before booking.",
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "date_str": {"type": "string", "description": "'today', 'tomorrow' or YYYY-MM-DD"},
            },
            "required": ["doctor_name", "date_str"],
        },
    },
    {
        "name": "find_patient",
        "description": "Look up an existing patient by mobile number to reuse their record.",
        "input_schema": {
            "type": "object",
            "properties": {"mobile": {"type": "string"}},
            "required": ["mobile"],
        },
    },
    {
        "name": "book_appointment",
        "description": "Book the appointment once you have name, 10-digit mobile, doctor, date and an available HH:MM time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "mobile": {"type": "string"},
                "doctor_name": {"type": "string"},
                "date_str": {"type": "string"},
                "time_str": {"type": "string", "description": "HH:MM 24-hour"},
            },
            "required": ["patient_name", "mobile", "doctor_name", "date_str", "time_str"],
        },
    },
    {
        "name": "end_call",
        "description": "End the call after confirming a booking or when the caller is done.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
]

DISPATCH = {
    "find_doctors": lambda i: find_doctors(),
    "available_slots": lambda i: available_slots(i.get("doctor_name"), i.get("date_str")),
    "find_patient": lambda i: find_patient(i.get("mobile")),
    "book_appointment": lambda i: book_appointment(
        i.get("patient_name"), i.get("mobile"), i.get("doctor_name"),
        i.get("date_str"), i.get("time_str"),
    ),
}


def run_tool(name, tool_input):
    handler = DISPATCH.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        return handler(tool_input or {})
    except Exception as exc:
        return {"error": str(exc)}
