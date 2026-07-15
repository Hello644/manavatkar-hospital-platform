import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models
from django.utils import timezone


class StaffProfile(models.Model):
    """Employment/attendance facts for a user. Login identity + PIN live on the
    User; this holds roster-relevant attributes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile"
    )
    designation = models.CharField(max_length=120, blank=True)
    department = models.CharField(max_length=120, blank=True)
    # Visiting consultants / part-timers should not pollute absentee dashboards.
    is_punch_exempt = models.BooleanField(default=False)
    joined_on = models.DateField(null=True, blank=True)
    exited_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__first_name", "user__last_name", "user__username"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def has_biometric_consent(self):
        consent = self.consents.order_by("-recorded_at").first()
        return bool(consent and consent.consent_given and not consent.withdrawn_at)


class Shift(models.Model):
    """A named shift template. If end <= start the shift crosses midnight."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=80, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["start_time"]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    @property
    def crosses_midnight(self):
        return self.end_time <= self.start_time


class ShiftInstance(models.Model):
    """A concrete roster assignment with ABSOLUTE start/end timestamps, so a
    07:05 OUT correctly credits yesterday's night shift (the midnight problem)."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        LEAVE = "leave", "On leave"
        OFF = "off", "Off / holiday"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="shift_instances")
    shift = models.ForeignKey(Shift, on_delete=models.PROTECT, related_name="instances")
    date = models.DateField(db_index=True, help_text="Roster date the shift belongs to")
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SCHEDULED)
    is_on_duty = models.BooleanField(default=False, help_text="Called in off-roster")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["window_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "shift", "date"], name="uniq_shift_instance"
            )
        ]
        indexes = [models.Index(fields=["date", "status"])]

    def __str__(self):
        return f"{self.staff.display_name} · {self.shift.name} · {self.date}"


class PunchEvent(models.Model):
    """A raw, DIRECTION-LESS timestamped punch. IN/OUT is derived later and never
    written back here — corrections re-run the derivation, not the raw events."""

    class Source(models.TextChoices):
        FACE = "face", "Face"
        PIN = "pin", "PIN"
        MANUAL = "manual", "Manual (admin)"
        BACK_ENTRY = "back_entry", "Back-dated entry"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(
        StaffProfile, null=True, blank=True, on_delete=models.SET_NULL, related_name="punches"
    )
    event_time = models.DateTimeField(db_index=True)
    device_time = models.DateTimeField(null=True, blank=True, help_text="Kiosk clock at capture")
    source = models.CharField(max_length=12, choices=Source.choices, default=Source.FACE)
    device = models.CharField(max_length=64, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    photo = models.FileField(upload_to="punch_photos/%Y/%m/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_time"]
        indexes = [models.Index(fields=["staff", "event_time"])]

    def __str__(self):
        who = self.staff.display_name if self.staff else "UNKNOWN"
        return f"{who} @ {self.event_time:%Y-%m-%d %H:%M} ({self.source})"


class AttendanceRecord(models.Model):
    """Derived, re-runnable IN/OUT interpretation for a shift instance."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"

    shift_instance = models.OneToOneField(
        ShiftInstance, on_delete=models.CASCADE, related_name="attendance"
    )
    first_in = models.DateTimeField(null=True, blank=True)
    last_out = models.DateTimeField(null=True, blank=True)
    punch_count = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ABSENT)
    worked_minutes = models.PositiveIntegerField(default=0)
    derived_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.shift_instance} → {self.status}"


class ConsentRecord(models.Model):
    """DPDP consent registry. Decliners use PIN-only with no adverse consequence."""

    class Method(models.TextChoices):
        BIOMETRIC = "biometric", "Biometric (face)"
        PIN = "pin", "PIN only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="consents")
    consent_given = models.BooleanField(default=False)
    method = models.CharField(max_length=12, choices=Method.choices, default=Method.PIN)
    notice_version = models.CharField(max_length=64, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="consents_recorded",
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-recorded_at"]

    def __str__(self):
        return f"{self.staff.display_name} · {self.get_method_display()}"


class FaceEnrollment(models.Model):
    """ArcFace embedding(s) for a staff member. Stored in Postgres; the face
    service does brute-force cosine matching. Purged within 30 days of exit."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="enrollments")
    embedding = models.JSONField(help_text="512-d ArcFace vector")
    reference_photo = models.FileField(upload_to="face_refs/", null=True, blank=True)
    quality = models.FloatField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Enrollment {self.staff.display_name}"


class LeaveType(models.Model):
    name = models.CharField(max_length=60, unique=True)
    is_paid = models.BooleanField(default=True)
    default_days = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return self.name


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="leave_requests")
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    from_date = models.DateField()
    to_date = models.DateField()
    reason = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="leaves_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.staff.display_name} {self.from_date}→{self.to_date} ({self.status})"

    @property
    def days(self):
        return (self.to_date - self.from_date).days + 1


class ShiftSwapRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shift_instance = models.ForeignKey(ShiftInstance, on_delete=models.CASCADE, related_name="swap_requests")
    to_staff = models.ForeignKey(StaffProfile, on_delete=models.CASCADE, related_name="swap_offers")
    reason = models.CharField(max_length=240, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="swaps_decided",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Swap {self.shift_instance} → {self.to_staff.display_name}"


class RegularizationRequest(models.Model):
    """Missed-punch auto-close → admin regularization queue (mandatory reason)."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    shift_instance = models.ForeignKey(
        ShiftInstance, on_delete=models.CASCADE, related_name="regularizations"
    )
    reason = models.CharField(max_length=240)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.OPEN)
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="regularizations_raised",
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="regularizations_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Regularize {self.shift_instance} ({self.status})"


for _model in (StaffProfile, Shift, ShiftInstance, PunchEvent, ConsentRecord,
               FaceEnrollment, LeaveRequest, ShiftSwapRequest, RegularizationRequest):
    auditlog.register(_model)
