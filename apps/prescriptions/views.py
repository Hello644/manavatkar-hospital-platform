from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.accounts.permissions import DOCTOR_ROLES, role_required, user_in_roles
from apps.opd.models import Visit
from apps.patients.models import Patient

from . import services
from .forms import PrescriptionHeaderForm
from .models import Drug, Prescription


def _doctor_for(request):
    return getattr(request.user, "doctor_profile", None)


def _resolve_drug(text):
    """Match a typed row to a formulary Drug (by printed label, brand or generic),
    else return None so it is stored as free text."""
    text = (text or "").strip()
    if not text:
        return None
    for drug in Drug.objects.filter(is_active=True):
        if text.lower() in (drug.label.lower(), (drug.brand_name or "").lower(), drug.generic_name.lower()):
            return drug
    return None


def _parse_rows(request):
    specs = []
    texts = request.POST.getlist("drug_text")
    dosages = request.POST.getlist("dosage")
    durations = request.POST.getlist("duration_days")
    instructions = request.POST.getlist("instructions")
    for i, text in enumerate(texts):
        text = (text or "").strip()
        if not text:
            continue
        duration = durations[i] if i < len(durations) else ""
        specs.append(
            {
                "drug": _resolve_drug(text),
                "drug_text": text,
                "dosage": dosages[i].strip() if i < len(dosages) else "",
                "duration_days": int(duration) if str(duration).strip().isdigit() else None,
                "instructions": instructions[i].strip() if i < len(instructions) else "",
            }
        )
    return specs


@role_required(*DOCTOR_ROLES)
def compose(request, visit_pk):
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=visit_pk)
    profile = _doctor_for(request)
    is_admin = user_in_roles(request.user, ("admin",)) or request.user.is_superuser
    if not is_admin and (profile is None or visit.doctor_id != profile.pk):
        raise PermissionDenied

    prescriber = visit.doctor
    if not prescriber.can_prescribe_on(timezone.localdate()):
        messages.warning(
            request,
            f"{prescriber.display_name} is not enabled to prescribe "
            "(needs a registration number and prescribing enabled).",
        )
        return redirect("opd:visit_detail", pk=visit.pk)

    header = PrescriptionHeaderForm(request.POST or None)
    conflicts = []
    specs = []
    if request.method == "POST" and header.is_valid():
        specs = _parse_rows(request)
        if not specs:
            messages.warning(request, "Add at least one medicine.")
        else:
            override_reason = header.cleaned_data.get("allergy_override_reason", "")
            conflicts = services.allergy_conflicts(visit.patient, specs)
            if conflicts and not override_reason:
                messages.error(
                    request,
                    "Allergy conflict — enter an override reason to proceed.",
                )
            else:
                rx = services.create_prescription(
                    patient=visit.patient,
                    doctor=prescriber,
                    user=request.user,
                    visit=visit,
                    diagnosis=header.cleaned_data["diagnosis"],
                    advice=header.cleaned_data["advice"],
                    followup_days=header.cleaned_data.get("followup_days"),
                    item_specs=specs,
                    allergy_override_reason=override_reason,
                )
                messages.success(request, f"Prescription {rx.short_id} saved.")
                return redirect("prescriptions:detail", pk=rx.pk)

    return render(
        request,
        "prescriptions/composer.html",
        {
            "visit": visit,
            "patient": visit.patient,
            "doctor": prescriber,
            "header": header,
            "formulary": Drug.objects.filter(is_active=True).order_by("generic_name"),
            "allergies": visit.patient.allergies.all(),
            "conflicts": conflicts,
            "rows": _parse_rows(request) if request.method == "POST" else [],
        },
    )


@role_required(*DOCTOR_ROLES)
def formulary_search(request):
    results = services.search_formulary(request.GET.get("q", ""))
    return JsonResponse(
        {"results": [{"id": str(d.id), "label": d.label, "schedule": d.schedule} for d in results]}
    )


@role_required("doctor", "nurse", "receptionist", "admin")
def detail(request, pk):
    rx = get_object_or_404(
        Prescription.objects.select_related("patient", "doctor").prefetch_related("items"),
        pk=pk,
    )
    return render(request, "prescriptions/detail.html", {"rx": rx})


@role_required("doctor", "nurse", "receptionist", "admin")
def print_view(request, pk):
    rx = get_object_or_404(
        Prescription.objects.select_related("patient", "doctor", "visit").prefetch_related(
            "items__drug"
        ),
        pk=pk,
    )
    schedules = {item.drug.schedule for item in rx.items.all() if item.drug}
    return render(
        request,
        "prescriptions/print.html",
        {
            "rx": rx,
            "has_h1": Drug.Schedule.H1 in schedules,
            "has_x": Drug.Schedule.X in schedules,
            "is_mlc": bool(rx.visit and rx.visit.is_mlc),
        },
    )
