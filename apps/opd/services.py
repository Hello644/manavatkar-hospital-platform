from django.db import transaction
from django.utils import timezone

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


@transaction.atomic
def call_next(doctor):
    visit = (
        Visit.objects.select_for_update()
        .filter(
            doctor=doctor,
            visit_date=timezone.localdate(),
            status__in=QUEUE_STATUSES,
        )
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


def start_consult(visit):
    now = timezone.now()
    visit.status = Visit.Status.IN_CONSULT
    visit.called_at = visit.called_at or now
    visit.consult_started_at = now
    visit.save(update_fields=["status", "called_at", "consult_started_at"])
    return visit


def skip(visit):
    visit.skip_count += 1
    if visit.skip_count >= 2:
        visit.status = Visit.Status.PARKED
    else:
        visit.status = (
            Visit.Status.VITALS_DONE if visit.vitals_at else Visit.Status.WAITING
        )
    visit.save(update_fields=["skip_count", "status"])
    return visit


def hold(visit):
    visit.status = Visit.Status.ON_HOLD
    visit.save(update_fields=["status"])
    return visit


def resume(visit):
    visit.status = Visit.Status.VITALS_DONE if visit.vitals_at else Visit.Status.WAITING
    visit.priority = max(visit.priority, PRIORITY_RESUMED)
    visit.save(update_fields=["status", "priority"])
    return visit


def mark_no_show(visit):
    visit.status = Visit.Status.NO_SHOW
    visit.save(update_fields=["status"])
    return visit


def complete(visit, *, disposition, disposition_note="", followup_days=None, referred_to=""):
    visit.status = Visit.Status.COMPLETED
    visit.disposition = disposition
    visit.disposition_note = disposition_note
    visit.followup_days = followup_days
    visit.referred_to = referred_to
    visit.completed_at = timezone.now()
    visit.full_clean()
    visit.save()
    return visit
