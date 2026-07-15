import base64
import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import (
    ATTENDANCE_ADMIN_ROLES,
    ATTENDANCE_VIEW_ROLES,
    role_required,
)

from . import faceclient, services
from .models import (
    FaceEnrollment,
    LeaveRequest,
    LeaveType,
    PunchEvent,
    RegularizationRequest,
    ShiftInstance,
    StaffProfile,
)

User = get_user_model()


# --------------------------------------------------------------- kiosk / punch

def _kiosk_authed(request):
    token = settings.KIOSK_DEVICE_TOKEN
    if not token:
        return False
    sent = request.headers.get("X-Kiosk-Token") or request.POST.get("token") or request.GET.get("token")
    return sent == token


def kiosk(request):
    """The attendance kiosk PWA shell. Token-gated so only the mounted tablet
    loads it."""
    if not _kiosk_authed(request):
        return HttpResponse("Kiosk token required.", status=401)
    return render(
        request,
        "attendance/kiosk.html",
        {"token": settings.KIOSK_DEVICE_TOKEN, "face_on": faceclient.is_configured()},
    )


def _save_photo(image_b64):
    try:
        header, _, data = image_b64.partition(",")
        raw = base64.b64decode(data or header)
    except (ValueError, TypeError):
        return None
    return ContentFile(raw, name=f"{uuid.uuid4().hex}.jpg")


@csrf_exempt
@require_POST
def punch(request):
    """Kiosk punch API (device-token auth). Accepts a PIN punch or a face frame.
    Stores a raw, direction-less event; IN/OUT is derived later."""
    if not _kiosk_authed(request):
        return JsonResponse({"status": "error", "message": "unauthorized"}, status=401)
    try:
        payload = json.loads(request.body or "{}")
    except ValueError:
        payload = request.POST
    device = payload.get("device", "")

    # PIN path (consent decliners + fallback) ---------------------------------
    if payload.get("pin") and payload.get("employee_code"):
        user = User.objects.filter(
            employee_code=payload["employee_code"], is_active=True
        ).select_related("staff_profile").first()
        if user is None or not hasattr(user, "staff_profile"):
            return JsonResponse({"status": "error", "message": "Unknown employee code"})
        if user.is_pin_locked():
            return JsonResponse({"status": "error", "message": "Locked, try later"})
        if not user.check_pin(payload["pin"]):
            user.register_pin_failure()
            return JsonResponse({"status": "error", "message": "PIN incorrect"})
        user.reset_pin_failures()
        services.record_punch(
            staff=user.staff_profile, source=PunchEvent.Source.PIN, device=device,
        )
        return JsonResponse({"status": "ok", "name": user.staff_profile.display_name})

    # Face path ---------------------------------------------------------------
    if payload.get("image"):
        if not faceclient.is_configured():
            return JsonResponse({"status": "error", "message": "Face off — use PIN"})
        result = faceclient.match(payload["image"])
        if not result.get("ok"):
            return JsonResponse({"status": "error", "message": result.get("error", "no match")})
        confidence = result.get("confidence", 0.0)
        margin = result.get("margin", 0.0)
        if confidence >= settings.FACE_MATCH_THRESHOLD and margin >= settings.FACE_MARGIN_THRESHOLD:
            staff = StaffProfile.objects.filter(pk=result.get("staff_id")).first()
            if staff is None:
                return JsonResponse({"status": "retry"})
            services.record_punch(
                staff=staff, source=PunchEvent.Source.FACE, device=device,
                confidence=confidence, photo=_save_photo(payload["image"]),
            )
            return JsonResponse({"status": "ok", "name": staff.display_name})
        if 0.32 <= confidence < settings.FACE_MATCH_THRESHOLD:
            staff = StaffProfile.objects.filter(pk=result.get("staff_id")).first()
            return JsonResponse({"status": "confirm", "name": staff.display_name if staff else ""})
        return JsonResponse({"status": "retry"})

    return JsonResponse({"status": "error", "message": "No PIN or image"})


# ------------------------------------------------------------------ dashboards

@role_required(*ATTENDANCE_VIEW_ROLES)
def board(request):
    return render(request, "attendance/board.html", {"present": services.who_is_in()})


@role_required(*ATTENDANCE_VIEW_ROLES)
def today(request):
    on_date = timezone.localdate()
    instances = (
        ShiftInstance.objects.filter(date=on_date)
        .select_related("staff", "shift")
        .prefetch_related("attendance")
    )
    late = [i for i in instances if i.status == ShiftInstance.Status.LATE]
    absent = [i for i in instances if i.status == ShiftInstance.Status.ABSENT]
    return render(
        request, "attendance/today.html",
        {"on_date": on_date, "late": late, "absent": absent, "instances": instances},
    )


@role_required(*ATTENDANCE_VIEW_ROLES)
def register(request):
    today_ = timezone.localdate()
    year = int(request.GET.get("year", today_.year))
    month = int(request.GET.get("month", today_.month))
    data = services.monthly_register(year, month)
    return render(
        request, "attendance/register.html",
        {"data": data, "year": year, "month": month, "day_range": range(1, data["days"] + 1)},
    )


@role_required(*ATTENDANCE_ADMIN_ROLES)
def payroll_export(request):
    today_ = timezone.localdate()
    year = int(request.GET.get("year", today_.year))
    month = int(request.GET.get("month", today_.month))
    content = services.payroll_workbook(year, month)
    response = HttpResponse(
        content,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="attendance-{year}-{month:02d}.xlsx"'
    return response


# ---------------------------------------------------------- regularization

@role_required(*ATTENDANCE_ADMIN_ROLES)
def regularization_queue(request):
    if request.method == "POST":
        services.close_missing_punches()
        messages.success(request, "Scanned for missing punches.")
        return redirect("attendance:regularization")
    open_items = RegularizationRequest.objects.filter(
        status=RegularizationRequest.Status.OPEN
    ).select_related("shift_instance__staff", "shift_instance__shift")
    return render(request, "attendance/regularization.html", {"items": open_items})


@role_required(*ATTENDANCE_ADMIN_ROLES)
@require_POST
def regularization_resolve(request, pk):
    item = get_object_or_404(RegularizationRequest, pk=pk)
    decision = request.POST.get("decision")
    reason = request.POST.get("reason", "").strip()
    if not reason:
        messages.warning(request, "A reason is required.")
        return redirect("attendance:regularization")
    item.reason = reason
    item.status = (
        RegularizationRequest.Status.RESOLVED if decision == "resolve"
        else RegularizationRequest.Status.REJECTED
    )
    item.resolved_by = request.user
    item.resolved_at = timezone.now()
    item.save()
    if decision == "resolve":
        instance = item.shift_instance
        instance.status = ShiftInstance.Status.PRESENT
        instance.save(update_fields=["status"])
    messages.success(request, "Regularization updated.")
    return redirect("attendance:regularization")


# --------------------------------------------------------------------- leave

@role_required(*ATTENDANCE_ADMIN_ROLES)
def leave_queue(request):
    pending = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.PENDING
    ).select_related("staff", "leave_type")
    return render(request, "attendance/leave.html", {"pending": pending})


@role_required(*ATTENDANCE_ADMIN_ROLES)
@require_POST
def leave_decide(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    leave.status = (
        LeaveRequest.Status.APPROVED if request.POST.get("decision") == "approve"
        else LeaveRequest.Status.REJECTED
    )
    leave.decided_by = request.user
    leave.decided_at = timezone.now()
    leave.save()
    if leave.status == LeaveRequest.Status.APPROVED:
        leave.staff.shift_instances.filter(
            date__gte=leave.from_date, date__lte=leave.to_date
        ).update(status=ShiftInstance.Status.LEAVE)
    messages.success(request, f"Leave {leave.status}.")
    return redirect("attendance:leave_queue")


# ---------------------------------------------------------------- enrollment

@role_required(*ATTENDANCE_ADMIN_ROLES)
def enroll(request, staff_id):
    staff = get_object_or_404(StaffProfile, pk=staff_id)
    if request.method == "POST":
        image = request.POST.get("image", "")
        result = faceclient.embed(image)
        if not result.get("ok"):
            messages.warning(request, result.get("error", "Enrollment failed."))
        else:
            FaceEnrollment.objects.create(
                staff=staff, embedding=result["embedding"],
                quality=result.get("quality"), reference_photo=_save_photo(image),
            )
            messages.success(request, f"Enrolled a sample for {staff.display_name}.")
        return redirect("attendance:enroll", staff_id=staff.pk)
    return render(
        request, "attendance/enroll.html",
        {"staff": staff, "samples": staff.enrollments.count(), "face_on": faceclient.is_configured()},
    )
