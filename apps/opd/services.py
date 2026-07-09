from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import DoctorProfile

from .models import (
    PRIORITY_APPOINTMENT,
    PRIORITY_RESUMED,
    PRIORITY_WALK_IN,
    Appointment,
    Receipt,
    ReceiptSequence,
    TokenSequence,
    Visit,
)


QUEUE_STATUSES = [Visit.Status.WAITING, Visit.Status.VITALS_DONE]


def token_prefix(doctor):
    label = (doctor.room_label or "").strip()
    return label[:1].upper() if label else "T"


@transaction.atomic
def next_token(doctor, on_date):
    sequence, _created = TokenSequence.objects.select_for_update().get_or_create(
        doctor=doctor, date=on_date, defaults={"last_value": 0}
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])
    return sequence.last_value, f"{token_prefix(doctor)}-{sequence.last_value:03d}"


@transaction.atomic
def next_receipt_no(on_date=None):
    on_date = on_date or timezone.localdate()
    year = on_date.year % 100
    sequence, _created = ReceiptSequence.objects.select_for_update().get_or_create(
        year=year, defaults={"last_value": 0}
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])
    return f"RCT-{year:02d}-{sequence.last_value:06d}"


@transaction.atomic
def create_visit(
    *,
    patient,
    doctor,
    user,
    source=Visit.Source.WALK_IN,
    is_emergency=False,
    is_mlc=False,
    mlc_brought_by="",
    mlc_police_station="",
    mlc_notes="",
    fee_amount=None,
    payment_mode="",
    appointment=None,
):
    on_date = timezone.localdate()
    token_number, token_label = next_token(doctor, on_date)
    visit = Visit(
        patient=patient,
        doctor=doctor,
        visit_date=on_date,
        token_number=token_number,
        token_label=token_label,
        source=source,
        is_emergency=is_emergency,
        priority=PRIORITY_APPOINTMENT if source == Visit.Source.APPOINTMENT else PRIORITY_WALK_IN,
        is_mlc=is_mlc,
        mlc_brought_by=mlc_brought_by,
        mlc_police_station=mlc_police_station,
        mlc_notes=mlc_notes,
        created_by=user,
    )
    visit.full_clean()
    visit.save()

    receipt = None
    if fee_amount and fee_amount > 0 and payment_mode:
        receipt = Receipt.objects.create(
            visit=visit,
            receipt_no=next_receipt_no(on_date),
            amount=fee_amount,
            mode=payment_mode,
            created_by=user,
        )

    if appointment is not None:
        appointment.status = Appointment.Status.CHECKED_IN
        appointment.visit = visit
        appointment.save(update_fields=["status", "visit", "updated_at"])

    return visit, receipt


def waiting_queue(doctor, on_date=None):
    on_date = on_date or timezone.localdate()
    return (
        Visit.objects.filter(doctor=doctor, visit_date=on_date, status__in=QUEUE_STATUSES)
        .select_related("patient")
        .order_by("-priority", "skip_count", "registered_at")
    )


def current_consult(doctor, on_date=None):
    on_date = on_date or timezone.localdate()
    return (
        Visit.objects.filter(
            doctor=doctor, visit_date=on_date, status=Visit.Status.IN_CONSULT
        )
        .select_related("patient")
        .order_by("-called_at")
        .first()
    )


def _lock_doctor(doctor_id):
    """Serialize consult-promotion for a doctor so the single-consult invariant
    holds under concurrent tabs / double-submits. Locking absent rows does not
    work in SQL, so we lock the doctor row itself as the mutex."""
    return DoctorProfile.objects.select_for_update().get(pk=doctor_id)


def _current_in_consult(doctor, on_date):
    return Visit.objects.filter(
        doctor=doctor, visit_date=on_date, status=Visit.Status.IN_CONSULT
    ).first()


@transaction.atomic
def call_next(doctor):
    on_date = timezone.localdate()
    _lock_doctor(doctor.pk)
    if _current_in_consult(doctor, on_date) is not None:
        # Someone is already in consult; refuse rather than pull a second patient.
        return None
    visit = (
        Visit.objects.select_for_update()
        .filter(doctor=doctor, visit_date=on_date, status__in=QUEUE_STATUSES)
        .order_by("-priority", "skip_count", "registered_at")
        .first()
    )
    if visit is None:
        return None
    now = timezone.now()
    visit.status = Visit.Status.IN_CONSULT
    visit.called_at = now
    visit.consult_started_at = now
    visit.save(update_fields=["status", "called_at", "consult_started_at"])
    return visit


def recall(visit):
    visit.called_at = timezone.now()
    visit.save(update_fields=["called_at"])
    return visit


@transaction.atomic
def start_consult(visit):
    """Promote a specific queued visit into consult. Returns None if another
    patient is already in consult for that doctor."""
    _lock_doctor(visit.doctor_id)
    locked = Visit.objects.select_for_update().get(pk=visit.pk)
    existing = _current_in_consult(locked.doctor, locked.visit_date)
    if existing is not None and existing.pk != locked.pk:
        return None
    now = timezone.now()
    locked.status = Visit.Status.IN_CONSULT
    locked.called_at = locked.called_at or now
    locked.consult_started_at = now
    locked.save(update_fields=["status", "called_at", "consult_started_at"])
    return locked


@transaction.atomic
def skip(visit):
    locked = Visit.objects.select_for_update().get(pk=visit.pk)
    if not locked.is_in_queue:
        return locked
    locked.skip_count += 1
    if locked.skip_count >= 2:
        locked.status = Visit.Status.PARKED
    else:
        locked.status = (
            Visit.Status.VITALS_DONE if locked.vitals_at else Visit.Status.WAITING
        )
    locked.save(update_fields=["skip_count", "status"])
    return locked


@transaction.atomic
def hold(visit):
    locked = Visit.objects.select_for_update().get(pk=visit.pk)
    if locked.status != Visit.Status.IN_CONSULT:
        return locked
    locked.status = Visit.Status.ON_HOLD
    locked.save(update_fields=["status"])
    return locked


@transaction.atomic
def resume(visit):
    locked = Visit.objects.select_for_update().get(pk=visit.pk)
    if locked.status not in {Visit.Status.ON_HOLD, Visit.Status.PARKED}:
        return locked
    locked.status = Visit.Status.VITALS_DONE if locked.vitals_at else Visit.Status.WAITING
    locked.priority = max(locked.priority, PRIORITY_RESUMED)
    locked.save(update_fields=["status", "priority"])
    return locked


@transaction.atomic
def mark_no_show(visit):
    locked = Visit.objects.select_for_update().get(pk=visit.pk)
    if locked.status not in {
        Visit.Status.WAITING,
        Visit.Status.VITALS_DONE,
        Visit.Status.PARKED,
        Visit.Status.ON_HOLD,
    }:
        return locked
    locked.status = Visit.Status.NO_SHOW
    locked.save(update_fields=["status"])
    return locked


def complete(visit, *, disposition, disposition_note="", followup_days=None, referred_to=""):
    visit.status = Visit.Status.COMPLETED
    visit.disposition = disposition
    visit.disposition_note = disposition_note
    visit.followup_days = followup_days
    visit.referred_to = referred_to
    if disposition == Visit.Disposition.FOLLOW_UP and followup_days:
        visit.followup_date = visit.visit_date + timedelta(days=followup_days)
    else:
        visit.followup_date = None
    visit.completed_at = timezone.now()
    visit.full_clean()
    visit.save()
    return visit


def followups_due(start_date, end_date, doctor=None):
    """Completed follow-up visits whose follow-up date falls in [start, end].
    Feeds the front-desk 'due today / this week' call list (PLAN §4)."""
    qs = (
        Visit.objects.filter(
            status=Visit.Status.COMPLETED,
            disposition=Visit.Disposition.FOLLOW_UP,
            followup_date__range=(start_date, end_date),
        )
        .select_related("patient", "doctor")
        .order_by("followup_date", "doctor__display_name")
    )
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    return qs


@transaction.atomic
def redirect_queue(from_doctor, to_doctor, on_date=None):
    """Move an absent doctor's live queue to another doctor, re-issuing each
    visit a fresh token in the target doctor's series. Returns the moved visits.
    Only patients still waiting/held (not in-consult/done) are moved."""
    if from_doctor.pk == to_doctor.pk:
        return []
    on_date = on_date or timezone.localdate()
    movable_statuses = [
        Visit.Status.WAITING,
        Visit.Status.VITALS_DONE,
        Visit.Status.ON_HOLD,
        Visit.Status.PARKED,
    ]
    visits = list(
        Visit.objects.select_for_update()
        .filter(doctor=from_doctor, visit_date=on_date, status__in=movable_statuses)
        .order_by("-priority", "skip_count", "registered_at")
    )
    for visit in visits:
        token_number, token_label = next_token(to_doctor, on_date)
        visit.doctor = to_doctor
        visit.token_number = token_number
        visit.token_label = token_label
        visit.save(update_fields=["doctor", "token_number", "token_label"])
    return visits
