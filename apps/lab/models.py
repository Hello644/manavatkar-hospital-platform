import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient


class LabTest(models.Model):
    """Catalog of orderable tests. Grows from real usage via the composer's
    free-text fallback, like the drug formulary."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160, unique=True)
    short_code = models.CharField(max_length=24, blank=True)
    category = models.CharField(max_length=80, blank=True)
    sample_type = models.CharField(max_length=60, blank=True, help_text="blood, urine, ...")
    default_unit = models.CharField(max_length=40, blank=True)
    reference_range = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["name"]), models.Index(fields=["short_code"])]

    def __str__(self):
        return self.name

    @property
    def label(self):
        return f"{self.name} ({self.short_code})" if self.short_code else self.name


class LabOrder(models.Model):
    class Status(models.TextChoices):
        ORDERED = "ordered", "Ordered"
        COLLECTED = "collected", "Sample collected"
        REPORTED = "reported", "Reported"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="lab_orders")
    visit = models.ForeignKey(
        "opd.Visit", null=True, blank=True, on_delete=models.SET_NULL, related_name="lab_orders"
    )
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name="lab_orders")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ORDERED)
    indication = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lab_orders_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"]), models.Index(fields=["status"])]

    def __str__(self):
        return f"Lab {self.short_id} · {self.patient.full_name}"

    @property
    def short_id(self):
        return str(self.id)[:8].upper()


class LabOrderItem(models.Model):
    class Flag(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"
        LOW = "low", "Low"
        ABNORMAL = "abnormal", "Abnormal"

    order = models.ForeignKey(LabOrder, on_delete=models.CASCADE, related_name="items")
    test = models.ForeignKey(LabTest, null=True, blank=True, on_delete=models.SET_NULL)
    test_text = models.CharField(max_length=160)
    result_value = models.CharField(max_length=120, blank=True)
    result_unit = models.CharField(max_length=40, blank=True)
    reference_range = models.CharField(max_length=80, blank=True)
    flag = models.CharField(max_length=12, choices=Flag.choices, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.test_text


auditlog.register(LabTest)
auditlog.register(LabOrder)
auditlog.register(LabOrderItem)
