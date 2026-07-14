import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient


class Drug(models.Model):
    """The hospital's own curated formulary (PLAN §5). Grown from real usage via
    the composer's free-text fallback -> admin add-queue."""

    class Schedule(models.TextChoices):
        OTC = "otc", "OTC / general"
        H = "h", "Schedule H"
        H1 = "h1", "Schedule H1"
        X = "x", "Schedule X"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    generic_name = models.CharField(max_length=180, help_text="INN / generic name")
    brand_name = models.CharField(max_length=180, blank=True)
    strength = models.CharField(max_length=60, blank=True, help_text="e.g. 500 mg")
    form = models.CharField(max_length=60, blank=True, help_text="tablet, syrup, ...")
    schedule = models.CharField(max_length=8, choices=Schedule.choices, default=Schedule.OTC)
    ingredients = models.CharField(
        max_length=240, blank=True, help_text="Comma-separated actives, for allergy/duplicate checks"
    )
    default_sig = models.CharField(max_length=120, blank=True, help_text="Default dosage signature")
    is_active = models.BooleanField(default=True)
    usage_count = models.PositiveIntegerField(default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["generic_name", "brand_name"]
        indexes = [
            models.Index(fields=["generic_name"]),
            models.Index(fields=["brand_name"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["generic_name", "brand_name", "strength", "form"],
                name="uniq_drug_identity",
            )
        ]

    def __str__(self):
        label = self.brand_name or self.generic_name
        return f"{label} {self.strength}".strip()

    @property
    def label(self):
        parts = [self.generic_name.upper()]
        if self.brand_name:
            parts.append(f"({self.brand_name})")
        if self.strength:
            parts.append(self.strength)
        return " ".join(parts)

    def ingredient_tokens(self):
        base = self.ingredients or self.generic_name
        return [t.strip().lower() for t in base.split(",") if t.strip()]


class Prescription(models.Model):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        REVISED = "revised", "Revised (superseded)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.ForeignKey(
        "opd.Visit", null=True, blank=True, on_delete=models.SET_NULL, related_name="prescriptions"
    )
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="prescriptions")
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name="prescriptions")
    diagnosis = models.CharField(max_length=240, blank=True)
    advice = models.TextField(blank=True)
    followup_days = models.PositiveSmallIntegerField(null=True, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ISSUED)
    version = models.PositiveSmallIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="revisions"
    )
    allergy_override_reason = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="prescriptions_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "-created_at"])]

    def __str__(self):
        return f"Rx {self.short_id} · {self.patient.full_name}"

    @property
    def short_id(self):
        return str(self.id)[:8].upper()

    @property
    def is_current(self):
        return self.status == self.Status.ISSUED


class PrescriptionItem(models.Model):
    prescription = models.ForeignKey(
        Prescription, on_delete=models.CASCADE, related_name="items"
    )
    drug = models.ForeignKey(Drug, null=True, blank=True, on_delete=models.SET_NULL)
    # Snapshot of what was printed, so the record is immutable even if the
    # formulary row later changes or is removed.
    drug_text = models.CharField(max_length=240)
    dosage = models.CharField(max_length=60, blank=True, help_text="e.g. 1-0-1 or BD")
    duration_days = models.PositiveSmallIntegerField(null=True, blank=True)
    quantity = models.PositiveSmallIntegerField(null=True, blank=True)
    instructions = models.CharField(max_length=180, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.drug_text

    def clean(self):
        if not self.drug and not self.drug_text:
            raise ValidationError("Each row needs a drug or free-text entry.")


auditlog.register(Drug)
auditlog.register(Prescription)
auditlog.register(PrescriptionItem)
