from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from .models import (
    AttendanceRecord,
    PunchEvent,
    RegularizationRequest,
    ShiftInstance,
    StaffProfile,
)

# How far outside the scheduled window a punch still counts toward the shift.
PUNCH_MARGIN = timedelta(hours=2)


def _aware(date, t):
    return timezone.make_aware(datetime.combine(date, t), timezone.get_current_timezone())


def make_shift_instance(staff, shift, on_date):
    """Create (or fetch) a shift instance with absolute timestamps. A shift whose
    end <= start crosses midnight, so its window_end lands on the next day."""
    window_start = _aware(on_date, shift.start_time)
    window_end = _aware(on_date, shift.end_time)
    if shift.crosses_midnight:
        window_end += timedelta(days=1)
    instance, _created = ShiftInstance.objects.get_or_create(
        staff=staff, shift=shift, date=on_date,
        defaults={"window_start": window_start, "window_end": window_end},
    )
    return instance


def record_punch(*, staff=None, event_time=None, source=PunchEvent.Source.FACE,
                 device="", confidence=None, photo=None, device_time=None):
    """Store a raw, direction-less punch. IN/OUT is derived later."""
    return PunchEvent.objects.create(
        staff=staff,
        event_time=event_time or timezone.now(),
        device_time=device_time,
        source=source,
        device=device,
        confidence=confidence,
        photo=photo,
    )


def _punches_for(instance):
    return list(
        PunchEvent.objects.filter(
            staff=instance.staff,
            event_time__gte=instance.window_start - PUNCH_MARGIN,
            event_time__lte=instance.window_end + PUNCH_MARGIN,
        ).order_by("event_time")
    )


@transaction.atomic
def derive_attendance(instance):
    """Recompute IN/OUT for a shift instance from its raw punches. Re-runnable —
    corrections re-run this, never edit the punch events."""
    punches = _punches_for(instance)
    record, _created = AttendanceRecord.objects.get_or_create(shift_instance=instance)
    record.punch_count = len(punches)
    if not punches:
        record.first_in = record.last_out = None
        record.worked_minutes = 0
        record.status = AttendanceRecord.Status.ABSENT
    else:
        record.first_in = punches[0].event_time
        record.last_out = punches[-1].event_time if len(punches) > 1 else None
        grace_end = instance.window_start + timedelta(minutes=instance.shift.grace_minutes)
        record.status = (
            AttendanceRecord.Status.LATE
            if record.first_in > grace_end
            else AttendanceRecord.Status.PRESENT
        )
        if record.last_out:
            record.worked_minutes = int((record.last_out - record.first_in).total_seconds() // 60)
        else:
            record.worked_minutes = 0
    record.save()

    if instance.status not in {ShiftInstance.Status.LEAVE, ShiftInstance.Status.OFF}:
        instance.status = {
            AttendanceRecord.Status.PRESENT: ShiftInstance.Status.PRESENT,
            AttendanceRecord.Status.LATE: ShiftInstance.Status.LATE,
            AttendanceRecord.Status.ABSENT: ShiftInstance.Status.ABSENT,
        }[record.status]
        instance.save(update_fields=["status"])
    return record


def who_is_in(now=None):
    """Muster list: staff whose punch count on the current day is odd (a
    direction-less toggle interpretation), i.e. currently inside."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    present = []
    for staff in StaffProfile.objects.filter(is_active=True):
        punches = list(
            PunchEvent.objects.filter(staff=staff, event_time__date=today).order_by("event_time")
        )
        if punches and len(punches) % 2 == 1:
            present.append({"staff": staff, "since": punches[-1].event_time})
    return present


@transaction.atomic
def close_missing_punches(on_date=None):
    """After a shift window ends with no punches, mark ABSENT and open a
    regularization request so the desk resolves it with a reason."""
    on_date = on_date or timezone.localdate()
    now = timezone.now()
    opened = 0
    instances = ShiftInstance.objects.filter(
        date=on_date, window_end__lt=now,
        status__in=[ShiftInstance.Status.SCHEDULED],
    ).select_related("staff", "shift")
    for instance in instances:
        record = derive_attendance(instance)
        if record.status == AttendanceRecord.Status.ABSENT and not instance.staff.is_punch_exempt:
            _obj, created = RegularizationRequest.objects.get_or_create(
                shift_instance=instance,
                defaults={"reason": "Auto: no punch recorded for scheduled shift"},
            )
            opened += 1 if created else 0
    return opened


def monthly_register(year, month):
    """staff × days grid of status codes for the given month."""
    import calendar

    days = calendar.monthrange(year, month)[1]
    codes = {
        ShiftInstance.Status.PRESENT: "P", ShiftInstance.Status.LATE: "L",
        ShiftInstance.Status.ABSENT: "A", ShiftInstance.Status.LEAVE: "Lv",
        ShiftInstance.Status.OFF: "O", ShiftInstance.Status.SCHEDULED: "-",
    }
    rows = []
    for staff in StaffProfile.objects.filter(is_active=True):
        instances = {
            inst.date.day: inst.status
            for inst in staff.shift_instances.filter(date__year=year, date__month=month)
        }
        cells = [codes.get(instances.get(d, ""), "") for d in range(1, days + 1)]
        present = sum(1 for c in cells if c in ("P", "L"))
        absent = cells.count("A")
        rows.append({"staff": staff, "cells": cells, "present": present, "absent": absent})
    return {"days": days, "rows": rows}


def payroll_workbook(year, month):
    """Build the monthly attendance register as an .xlsx workbook (bytes)."""
    import io

    from openpyxl import Workbook

    data = monthly_register(year, month)
    wb = Workbook()
    ws = wb.active
    ws.title = f"{year}-{month:02d}"
    header = ["Staff", "Designation"] + [str(d) for d in range(1, data["days"] + 1)] + ["Present", "Absent"]
    ws.append(header)
    for row in data["rows"]:
        ws.append(
            [row["staff"].display_name, row["staff"].designation]
            + row["cells"]
            + [row["present"], row["absent"]]
        )
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
