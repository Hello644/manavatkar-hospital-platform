from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import (
    CLINICAL_READ_ROLES,
    PATIENT_MANAGE_ROLES,
    role_required,
)

from .forms import PatientForm
from .models import Patient
from .services import find_possible_duplicates, normalize_mobile, normalize_name


@role_required(*CLINICAL_READ_ROLES)
def patient_list(request):
    query = (request.GET.get("q") or "").strip()
    patients = Patient.objects.filter(is_active=True)

    if query:
        mobile = normalize_mobile(query)
        if len(mobile) >= 6:
            patients = patients.filter(Q(mobile__icontains=mobile) | Q(uhid__icontains=query))
        else:
            name_query = normalize_name(query)
            patients = patients.filter(name_normalized__icontains=name_query)

    return render(
        request,
        "patients/patient_list.html",
        {"patients": patients[:50], "query": query},
    )


@role_required(*PATIENT_MANAGE_ROLES)
def patient_create(request):
    form = PatientForm(request.POST or None, user=request.user)
    duplicates = []
    if request.method == "POST" and form.is_valid():
        patient = form.save(commit=False)
        duplicates = list(find_possible_duplicates(patient))
        if duplicates and "confirm_save" not in request.POST:
            messages.warning(request, "Possible duplicate patients found. Review before saving.")
        else:
            patient.full_clean()
            patient.save()
            messages.success(request, f"Patient registered with UHID {patient.uhid}.")
            return redirect("patients:detail", pk=patient.pk)
    return render(
        request,
        "patients/patient_form.html",
        {"form": form, "duplicates": duplicates, "is_create": True},
    )


@role_required(*CLINICAL_READ_ROLES)
def patient_detail(request, pk):
    patient = get_object_or_404(Patient, pk=pk, is_active=True)
    return render(request, "patients/patient_detail.html", {"patient": patient})


@role_required(*PATIENT_MANAGE_ROLES)
def patient_update(request, pk):
    patient = get_object_or_404(Patient, pk=pk, is_active=True)
    form = PatientForm(request.POST or None, instance=patient, user=request.user)
    if request.method == "POST" and form.is_valid():
        patient = form.save()
        messages.success(request, "Patient details updated.")
        return redirect("patients:detail", pk=patient.pk)
    return render(
        request,
        "patients/patient_form.html",
        {"form": form, "patient": patient, "is_create": False},
    )

