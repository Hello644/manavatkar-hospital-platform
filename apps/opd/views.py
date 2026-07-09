from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import DoctorProfile
from apps.core.models import HospitalProfile
from apps.patients.models import Patient

from . import services
from .escpos import build_token_slip, send_to_printer
from .forms import (
    AppointmentForm,
    CancelDayForm,
    CompleteVisitForm,
    QuickUnknownPatientForm,
    RedirectQueueForm,
    RefundForm,
    VitalsForm,
    WalkInVisitForm,
)
from .models import Appointment, Receipt, Visit
from .permissions import (
    CLINICAL_READ_ROLES,
    DOCTOR_ROLES,
    FRONT_DESK_ROLES,
    NURSE_ROLES,
    REPORT_ROLES,
    role_required,
    user_in_roles,
)


def parse_date_param(request, default=None):
    raw = request.GET.get("date") or request.POST.get("date") or ""
    try:
        return timezone.datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return default or timezone.localdate()


def resolve_doctor(request):
    doctor_id = request.GET.get("doctor") or request.POST.get("doctor_id")
    profile = getattr(request.user, "doctor_profile", None)
    if doctor_id and (user_in_roles(request.user, ("admin",)) or request.user.is_superuser):
        return get_object_or_404(DoctorProfile, pk=doctor_id)
    if profile is not None:
        return profile
    if doctor_id:
        return get_object_or_404(DoctorProfile, pk=doctor_id)
    return None


# ---------------------------------------------------------------- front desk


@role_required(*FRONT_DESK_ROLES)
def new_visit(request):
    patient = get_object_or_404(
        Patient, pk=request.GET.get("patient") or request.POST.get("patient"), is_active=True
    )
    appointment = None
    appointment_id = request.GET.get("appointment") or request.POST.get("appointment")
    if appointment_id:
        appointment = get_object_or_404(
            Appointment, pk=appointment_id, status=Appointment.Status.BOOKED
        )
        if appointment.patient_id != patient.pk:
            raise PermissionDenied

    form = WalkInVisitForm(
        request.POST or None,
        locked_doctor=appointment.doctor if appointment else None,
        patient=patient,
        initial={"is_mlc": request.GET.get("mlc") == "1", "is_emergency": request.GET.get("emergency") == "1"},
    )
    if request.method == "POST" and form.is_valid():
        doctor = appointment.doctor if appointment else form.cleaned_data["doctor"]
        visit, receipt = services.create_visit(
            patient=patient,
            doctor=doctor,
            user=request.user,
            source=Visit.Source.APPOINTMENT if appointment else Visit.Source.WALK_IN,
            is_emergency=form.cleaned_data["is_emergency"],
            is_mlc=form.cleaned_data["is_mlc"],
            mlc_brought_by=form.cleaned_data["mlc_brought_by"],
            mlc_police_station=form.cleaned_data["mlc_police_station"],
            mlc_notes=form.cleaned_data["mlc_notes"],
            fee_amount=form.cleaned_data.get("fee_amount"),
            payment_mode=(
                form.cleaned_data["payment_mode"]
                if form.cleaned_data["payment_mode"] != "free"
                else ""
            ),
            appointment=appointment,
        )
        messages.success(request, f"Token {visit.token_label} issued for {patient.full_name}.")
        return redirect("opd:slip", pk=visit.pk)

    doctor_fees = {
        str(profile.pk): str(profile.consult_fee)
        for profile in DoctorProfile.objects.all()
    }
    return render(
        request,
        "opd/new_visit.html",
        {
            "patient": patient,
            "form": form,
            "appointment": appointment,
            "doctor_fees": doctor_fees,
        },
    )


@role_required(*CLINICAL_READ_ROLES)
def visit_slip(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related("patient", "doctor"), pk=pk
    )
    receipt = visit.receipts.filter(is_refunded=False).order_by("created_at").first()
    return render(request, "opd/slip.html", {"visit": visit, "receipt": receipt})


@role_required(*CLINICAL_READ_ROLES)
def token_slip_escpos(request, pk):
    """Print the token on the thermal printer (server-driven ESC/POS). Streams to
    a network printer when configured, else returns raw bytes for a spooler."""
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=pk)
    payload = build_token_slip(visit, HospitalProfile.get_solo())
    host = settings.OPD_THERMAL_PRINTER_HOST
    if host:
        try:
            send_to_printer(payload, host, settings.OPD_THERMAL_PRINTER_PORT)
            messages.success(
                request, f"Token {visit.token_label} sent to the thermal printer."
            )
        except OSError as exc:
            messages.warning(
                request, f"Thermal printer unreachable ({exc}). Use the A4 slip instead."
            )
        return redirect("opd:slip", pk=visit.pk)
    response = HttpResponse(payload, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="token-{visit.token_label}.bin"'
    return response


@role_required(*FRONT_DESK_ROLES)
def mlc_quick_register(request):
    form = QuickUnknownPatientForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        patient = form.build_patient(request.user)
        patient.full_clean()
        patient.save()
        messages.warning(
            request,
            f"Unknown patient registered as {patient.uhid}. Update identity once known.",
        )
        return redirect(f"{reverse('opd:new_visit')}?patient={patient.pk}&mlc=1&emergency=1")
    return render(request, "opd/mlc_quick_register.html", {"form": form})


@login_required
def queue_board(request):
    today = timezone.localdate()
    doctors = DoctorProfile.objects.order_by("display_name")
    columns = []
    for doctor in doctors:
        visits_today = Visit.objects.filter(doctor=doctor, visit_date=today)
        columns.append(
            {
                "doctor": doctor,
                "now": services.current_consult(doctor, today),
                "queue": list(services.waiting_queue(doctor, today)[:12]),
                "held": list(
                    visits_today.filter(status=Visit.Status.ON_HOLD).select_related("patient")
                ),
                "parked": list(
                    visits_today.filter(status=Visit.Status.PARKED).select_related("patient")
                ),
                "done_count": visits_today.filter(status=Visit.Status.COMPLETED).count(),
            }
        )
    return render(request, "opd/queue_board.html", {"columns": columns, "today": today})


# -------------------------------------------------------------- appointments


@role_required(*FRONT_DESK_ROLES)
def appointment_list(request):
    on_date = parse_date_param(request)
    doctor_id = request.GET.get("doctor") or ""
    appointments = (
        Appointment.objects.filter(date=on_date)
        .select_related("patient", "doctor")
        .order_by("slot_time")
    )
    if doctor_id:
        appointments = appointments.filter(doctor_id=doctor_id)
    return render(
        request,
        "opd/appointments.html",
        {
            "appointments": appointments,
            "on_date": on_date,
            "doctors": DoctorProfile.objects.order_by("display_name"),
            "selected_doctor": doctor_id,
        },
    )


@role_required(*FRONT_DESK_ROLES)
def appointment_create(request):
    patient = get_object_or_404(
        Patient, pk=request.GET.get("patient") or request.POST.get("patient"), is_active=True
    )
    form = AppointmentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        appointment = form.save(commit=False)
        appointment.patient = patient
        appointment.created_by = request.user
        appointment.save()
        messages.success(
            request,
            f"Appointment booked for {patient.full_name} on {appointment.date} "
            f"at {appointment.slot_time:%H:%M}.",
        )
        return redirect(f"{reverse('opd:appointments')}?date={appointment.date.isoformat()}")
    return render(
        request, "opd/appointment_form.html", {"form": form, "patient": patient}
    )


@role_required(*FRONT_DESK_ROLES)
@require_POST
def appointment_cancel(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, status=Appointment.Status.BOOKED)
    appointment.status = Appointment.Status.CANCELLED
    appointment.cancelled_reason = request.POST.get("reason", "")[:240]
    appointment.save(update_fields=["status", "cancelled_reason", "updated_at"])
    messages.success(request, "Appointment cancelled.")
    return redirect(f"{reverse('opd:appointments')}?date={appointment.date.isoformat()}")


@role_required(*FRONT_DESK_ROLES)
@require_POST
def appointment_no_show(request, pk):
    appointment = get_object_or_404(Appointment, pk=pk, status=Appointment.Status.BOOKED)
    appointment.status = Appointment.Status.NO_SHOW
    appointment.save(update_fields=["status", "updated_at"])
    messages.success(request, "Marked as no-show.")
    return redirect(f"{reverse('opd:appointments')}?date={appointment.date.isoformat()}")


@role_required(*FRONT_DESK_ROLES)
def cancel_day(request):
    form = CancelDayForm(request.POST or None)
    cancelled = None
    if request.method == "POST" and form.is_valid():
        doctor = form.cleaned_data["doctor"]
        on_date = form.cleaned_data["date"]
        reason = form.cleaned_data["reason"]
        to_cancel = list(
            Appointment.objects.filter(
                doctor=doctor, date=on_date, status=Appointment.Status.BOOKED
            ).select_related("patient")
        )
        for appointment in to_cancel:
            appointment.status = Appointment.Status.CANCELLED
            appointment.cancelled_reason = reason
            appointment.save(update_fields=["status", "cancelled_reason", "updated_at"])
        cancelled = to_cancel
        messages.warning(
            request,
            f"Cancelled {len(to_cancel)} appointment(s) for {doctor} on {on_date}. "
            "Call the patients below.",
        )
    return render(request, "opd/cancel_day.html", {"form": form, "cancelled": cancelled})


@role_required(*FRONT_DESK_ROLES)
def queue_redirect(request):
    form = RedirectQueueForm(request.POST or None)
    moved = None
    if request.method == "POST" and form.is_valid():
        moved = services.redirect_queue(
            form.cleaned_data["from_doctor"], form.cleaned_data["to_doctor"]
        )
        messages.warning(
            request,
            f"Moved {len(moved)} waiting patient(s) to "
            f"{form.cleaned_data['to_doctor']} with new tokens.",
        )
    return render(request, "opd/queue_redirect.html", {"form": form, "moved": moved})


@role_required(*FRONT_DESK_ROLES)
def followup_list(request):
    start = parse_date_param(request)
    span = request.GET.get("span", "day")
    end = start + timedelta(days=6) if span == "week" else start
    followups = services.followups_due(start, end)
    return render(
        request,
        "opd/followup_list.html",
        {"followups": followups, "start": start, "end": end, "span": span},
    )


# --------------------------------------------------------------------- nurse


@role_required(*NURSE_ROLES)
def vitals_queue(request):
    today = timezone.localdate()
    pending = (
        Visit.objects.filter(visit_date=today, status=Visit.Status.WAITING)
        .select_related("patient", "doctor")
        .order_by("-priority", "registered_at")
    )
    done = (
        Visit.objects.filter(visit_date=today, status=Visit.Status.VITALS_DONE)
        .select_related("patient", "doctor")
        .order_by("-vitals_at")[:15]
    )
    return render(request, "opd/vitals_queue.html", {"pending": pending, "done": done})


@role_required(*NURSE_ROLES)
def vitals_entry(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related("patient", "doctor"), pk=pk
    )
    instance = getattr(visit, "vitals", None)
    form = VitalsForm(request.POST or None, instance=instance, visit=visit)
    if request.method == "POST" and form.is_valid():
        vitals = form.save(commit=False)
        vitals.visit = visit
        if instance is None:
            vitals.recorded_by = request.user
        vitals.save()
        if visit.status == Visit.Status.WAITING:
            visit.status = Visit.Status.VITALS_DONE
        visit.vitals_at = timezone.now()
        visit.save(update_fields=["status", "vitals_at"])
        messages.success(request, f"Vitals saved for token {visit.token_label}.")
        return redirect("opd:vitals_queue")
    allergies = visit.patient.allergies.all()
    return render(
        request,
        "opd/vitals_form.html",
        {"visit": visit, "form": form, "allergies": allergies},
    )


# -------------------------------------------------------------------- doctor


@role_required(*DOCTOR_ROLES)
def doctor_queue(request):
    doctor = resolve_doctor(request)
    if doctor is None:
        messages.warning(request, "No doctor profile linked to this account.")
        return redirect("dashboard")
    today = timezone.localdate()
    visits_today = Visit.objects.filter(doctor=doctor, visit_date=today)
    context = {
        "doctor": doctor,
        "now_visit": services.current_consult(doctor, today),
        "queue": list(services.waiting_queue(doctor, today)),
        "held": list(
            visits_today.filter(status=Visit.Status.ON_HOLD).select_related("patient")
        ),
        "parked": list(
            visits_today.filter(status=Visit.Status.PARKED).select_related("patient")
        ),
        "done_count": visits_today.filter(status=Visit.Status.COMPLETED).count(),
    }
    return render(request, "opd/doctor_queue.html", context)


@role_required(*DOCTOR_ROLES)
@require_POST
def queue_call_next(request):
    doctor = resolve_doctor(request)
    if doctor is None:
        raise PermissionDenied
    current = services.current_consult(doctor)
    if current is not None:
        messages.warning(
            request,
            f"Finish token {current.token_label} (complete, hold, or skip) before calling next.",
        )
        return redirect("opd:doctor_queue")
    visit = services.call_next(doctor)
    if visit is None:
        messages.warning(request, "Queue is empty.")
        return redirect("opd:doctor_queue")
    return redirect("opd:visit_detail", pk=visit.pk)


def get_actionable_visit(request, pk):
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=pk)
    profile = getattr(request.user, "doctor_profile", None)
    is_admin = user_in_roles(request.user, ("admin",)) or request.user.is_superuser
    if not is_admin and (profile is None or visit.doctor_id != profile.pk):
        raise PermissionDenied
    return visit


@role_required(*DOCTOR_ROLES)
@require_POST
def queue_action(request, pk, action):
    visit = get_actionable_visit(request, pk)
    if action == "recall" and visit.status == Visit.Status.IN_CONSULT:
        services.recall(visit)
        messages.success(request, f"Token {visit.token_label} re-announced.")
    elif action == "skip" and visit.is_in_queue:
        services.skip(visit)
        messages.success(request, f"Token {visit.token_label} skipped.")
    elif action == "hold" and visit.status == Visit.Status.IN_CONSULT:
        services.hold(visit)
        messages.success(request, f"Token {visit.token_label} on hold.")
    elif action == "resume" and visit.status in {Visit.Status.ON_HOLD, Visit.Status.PARKED}:
        services.resume(visit)
        messages.success(request, f"Token {visit.token_label} back in queue at front.")
    elif action == "start" and visit.is_in_queue:
        started = services.start_consult(visit)
        if started is None:
            messages.warning(
                request, "Another patient is already in consult. Finish them first."
            )
            return redirect("opd:doctor_queue")
        return redirect("opd:visit_detail", pk=visit.pk)
    elif action == "no_show" and visit.status in {
        Visit.Status.WAITING,
        Visit.Status.VITALS_DONE,
        Visit.Status.PARKED,
        Visit.Status.ON_HOLD,
    }:
        services.mark_no_show(visit)
        messages.success(request, f"Token {visit.token_label} marked no-show.")
    else:
        messages.warning(request, "That action is not available for this visit.")
    return redirect("opd:doctor_queue")


@role_required(*CLINICAL_READ_ROLES)
def visit_detail(request, pk):
    visit = get_object_or_404(
        Visit.objects.select_related("patient", "doctor"), pk=pk
    )
    patient = visit.patient
    past_visits = (
        patient.visits.filter(status=Visit.Status.COMPLETED)
        .exclude(pk=visit.pk)
        .select_related("doctor")
        .order_by("-visit_date")[:5]
    )
    complete_form = CompleteVisitForm()
    return render(
        request,
        "opd/visit_detail.html",
        {
            "visit": visit,
            "patient": patient,
            "vitals": getattr(visit, "vitals", None),
            "allergies": patient.allergies.all(),
            "chronic_conditions": patient.chronic_conditions.all(),
            "past_visits": past_visits,
            "complete_form": complete_form,
            "can_act": (
                user_in_roles(request.user, ("admin",))
                or request.user.is_superuser
                or getattr(getattr(request.user, "doctor_profile", None), "pk", None)
                == visit.doctor_id
            ),
        },
    )


@role_required(*DOCTOR_ROLES)
@require_POST
def visit_complete(request, pk):
    visit = get_actionable_visit(request, pk)
    if visit.status != Visit.Status.IN_CONSULT:
        messages.warning(request, "Only a visit in consult can be completed.")
        return redirect("opd:visit_detail", pk=visit.pk)
    form = CompleteVisitForm(request.POST)
    if not form.is_valid():
        messages.warning(request, "Choose a disposition to complete the visit.")
        return redirect("opd:visit_detail", pk=visit.pk)
    services.complete(
        visit,
        disposition=form.cleaned_data["disposition"],
        disposition_note=form.cleaned_data["disposition_note"],
        followup_days=form.cleaned_data["followup_days"],
        referred_to=form.cleaned_data["referred_to"],
    )
    messages.success(request, f"Visit {visit.token_label} completed.")
    if "complete_and_next" in request.POST:
        next_visit = services.call_next(visit.doctor)
        if next_visit is not None:
            return redirect("opd:visit_detail", pk=next_visit.pk)
        messages.warning(request, "Queue is empty.")
    return redirect("opd:doctor_queue")


# ------------------------------------------------------------------- display


def display(request):
    return render(
        request,
        "opd/display.html",
        {
            "announce_enabled": settings.OPD_ANNOUNCE_AUDIO,
            "announce_lang": settings.OPD_ANNOUNCE_LANG,
            "announce_base": f"{settings.STATIC_URL}announce/",
        },
    )


def display_data(request):
    today = timezone.localdate()
    payload = []
    doctor_ids = (
        Visit.objects.filter(visit_date=today).values_list("doctor_id", flat=True).distinct()
    )
    for doctor in DoctorProfile.objects.filter(pk__in=doctor_ids).order_by("display_name"):
        now_visit = services.current_consult(doctor, today)
        queue = services.waiting_queue(doctor, today)
        payload.append(
            {
                "doctor": doctor.display_name,
                "room": doctor.room_label,
                "now": now_visit.token_label if now_visit else None,
                "called_at": (
                    now_visit.called_at.isoformat()
                    if now_visit and now_visit.called_at
                    else None
                ),
                "next": [visit.token_label for visit in queue[:3]],
                "waiting_count": queue.count(),
            }
        )
    return JsonResponse({"generated_at": timezone.now().isoformat(), "doctors": payload})


# ------------------------------------------------------------------- reports


@role_required(*REPORT_ROLES)
def collection_register(request):
    on_date = parse_date_param(request)
    receipts = (
        Receipt.objects.filter(created_at__date=on_date)
        .select_related("visit__patient", "visit__doctor", "created_by")
        .order_by("receipt_no")
    )
    active = receipts.filter(is_refunded=False)
    totals = {
        "cash": active.filter(mode=Receipt.Mode.CASH).aggregate(total=Sum("amount"))["total"]
        or 0,
        "upi": active.filter(mode=Receipt.Mode.UPI).aggregate(total=Sum("amount"))["total"]
        or 0,
    }
    totals["all"] = totals["cash"] + totals["upi"]
    refunded_total = (
        receipts.filter(is_refunded=True).aggregate(total=Sum("amount"))["total"] or 0
    )
    doctor_counts = list(
        Visit.objects.filter(visit_date=on_date)
        .values("doctor__display_name")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status=Visit.Status.COMPLETED)),
            no_show=Count("id", filter=Q(status=Visit.Status.NO_SHOW)),
        )
        .order_by("doctor__display_name")
    )
    # Doctor-wise revenue (active receipts) — the first report the owner asks for
    # (PLAN §4). Keyed by the same visit_date as the counts so both share a day.
    revenue_by_doctor = {
        row["visit__doctor__display_name"]: row["revenue"]
        for row in Receipt.objects.filter(
            visit__visit_date=on_date, is_refunded=False
        )
        .values("visit__doctor__display_name")
        .annotate(revenue=Sum("amount"))
    }
    for row in doctor_counts:
        row["revenue"] = revenue_by_doctor.get(row["doctor__display_name"], 0)
    return render(
        request,
        "opd/collection_register.html",
        {
            "on_date": on_date,
            "receipts": receipts,
            "totals": totals,
            "refunded_total": refunded_total,
            "doctor_counts": doctor_counts,
            "refund_form": RefundForm(),
        },
    )


@role_required(*REPORT_ROLES)
@require_POST
def receipt_refund(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk, is_refunded=False)
    form = RefundForm(request.POST)
    if not form.is_valid():
        messages.warning(request, "A refund reason is required.")
    else:
        receipt.is_refunded = True
        receipt.refund_reason = form.cleaned_data["refund_reason"]
        receipt.refunded_at = timezone.now()
        receipt.refunded_by = request.user
        receipt.save(
            update_fields=["is_refunded", "refund_reason", "refunded_at", "refunded_by"]
        )
        messages.success(request, f"Receipt {receipt.receipt_no} refunded.")
    register_date = timezone.localtime(receipt.created_at).date()
    return redirect(
        f"{reverse('opd:collection_register')}?date={register_date.isoformat()}"
    )
