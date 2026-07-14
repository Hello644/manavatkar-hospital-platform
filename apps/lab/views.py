from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import (
    CLINICAL_READ_ROLES,
    DOCTOR_ROLES,
    LAB_STAFF_ROLES,
    role_required,
    user_in_roles,
)
from apps.opd.models import Visit

from . import services
from .models import LabOrder, LabTest


def _parse_test_rows(request):
    specs = []
    for text in request.POST.getlist("test_text"):
        text = (text or "").strip()
        if not text:
            continue
        specs.append({"test": services.resolve_test(text), "test_text": text})
    return specs


@role_required(*DOCTOR_ROLES)
def order_create(request, visit_pk):
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=visit_pk)
    profile = getattr(request.user, "doctor_profile", None)
    is_admin = user_in_roles(request.user, ("admin",)) or request.user.is_superuser
    if not is_admin and (profile is None or visit.doctor_id != profile.pk):
        raise PermissionDenied

    if request.method == "POST":
        specs = _parse_test_rows(request)
        if not specs:
            messages.warning(request, "Add at least one test.")
        else:
            order = services.create_lab_order(
                patient=visit.patient, doctor=visit.doctor, user=request.user, visit=visit,
                indication=request.POST.get("indication", "")[:240], test_specs=specs,
            )
            messages.success(request, f"Lab order {order.short_id} placed.")
            return redirect("lab:detail", pk=order.pk)

    return render(
        request,
        "lab/order_form.html",
        {"visit": visit, "tests": LabTest.objects.filter(is_active=True)},
    )


@role_required(*CLINICAL_READ_ROLES)
def detail(request, pk):
    order = get_object_or_404(
        LabOrder.objects.select_related("patient", "doctor", "visit").prefetch_related(
            "items__test"
        ),
        pk=pk,
    )
    return render(
        request,
        "lab/detail.html",
        {
            "order": order,
            "can_edit": user_in_roles(request.user, LAB_STAFF_ROLES),
            "flag_choices": order.items.model.Flag.choices,
        },
    )


@role_required(*LAB_STAFF_ROLES)
def save_results(request, pk):
    order = get_object_or_404(LabOrder, pk=pk)
    if request.method != "POST":
        return redirect("lab:detail", pk=order.pk)
    rows = {}
    for item in order.items.all():
        key = str(item.pk)
        rows[key] = {
            "result_value": request.POST.get(f"value_{key}", "").strip(),
            "result_unit": request.POST.get(f"unit_{key}", "").strip(),
            "reference_range": request.POST.get(f"ref_{key}", "").strip(),
            "flag": request.POST.get(f"flag_{key}", "").strip(),
        }
    services.save_results(order, rows, mark_reported="report" in request.POST)
    messages.success(request, f"Results saved for {order.short_id}.")
    return redirect("lab:detail", pk=order.pk)


@role_required(*LAB_STAFF_ROLES)
def set_status(request, pk, status):
    order = get_object_or_404(LabOrder, pk=pk)
    valid = {LabOrder.Status.COLLECTED, LabOrder.Status.CANCELLED, LabOrder.Status.ORDERED}
    if request.method == "POST" and status in valid:
        services.set_status(order, status)
        messages.success(request, f"Lab order {order.short_id} marked {status}.")
    return redirect("lab:detail", pk=order.pk)


@role_required(*DOCTOR_ROLES)
def test_search(request):
    results = services.search_tests(request.GET.get("q", ""))
    return JsonResponse({"results": [{"id": str(t.id), "label": t.label} for t in results]})
