import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .services import generate_uhid, normalize_name


class PatientSequence(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self):
        return f"{self.year}: {self.last_value}"


class Patient(models.Model):
    class Sex(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        OTHER = "O", "Other"

    class PreferredLanguage(models.TextChoices):
        ENGLISH = "en", "English"
        HINDI = "hi", "Hindi"
        MARATHI = "mr", "Marathi"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    uhid = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    full_name = models.CharField(max_length=180)
    name_normalized = models.CharField(max_length=180, db_index=True, editable=False)
    mobile = models.CharField(max_length=10, blank=True, db_index=True)
    no_phone = models.BooleanField(default=False)
    dob = models.DateField(null=True, blank=True)
    dob_estimated = models.BooleanField(default=False)
    age_years_at_registration = models.PositiveSmallIntegerField(null=True, blank=True)
    sex = models.CharField(max_length=1, choices=Sex.choices)

    address_line = models.CharField(max_length=240, blank=True)
    area_village = models.CharField(max_length=120, blank=True)
    city = models.CharField(max_length=120, blank=True, default="Bhusawal")
    district = models.CharField(max_length=120, blank=True, default="Jalgaon")
    pincode = models.CharField(max_length=6, blank=True)
    abha_number = models.CharField(max_length=32, blank=True)
    abha_address = models.CharField(max_length=120, blank=True)
    blood_group = models.CharField(max_length=8, blank=True)
    email = models.EmailField(blank=True)
    aadhaar_last4 = models.CharField(max_length=4, blank=True)
    preferred_language = models.CharField(
        max_length=2,
        choices=PreferredLanguage.choices,
        default=PreferredLanguage.MARATHI,
    )

    guardian_name = models.CharField(max_length=180, blank=True)
    guardian_relationship = models.CharField(max_length=80, blank=True)
    emergency_contact_name = models.CharField(max_length=180, blank=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True)
    referral_source = models.CharField(max_length=120, blank=True)
    old_file_number = models.CharField(max_length=64, blank=True, db_index=True)

    privacy_notice_accepted = models.BooleanField(default=False)
    privacy_notice_version = models.CharField(max_length=64, blank=True)
    privacy_notice_accepted_at = models.DateTimeField(null=True, blank=True)
    # Emergency path for unknown/unconscious patients (e.g. MLC): the notice
    # cannot be given, so acceptance is deferred until identity is known.
    privacy_notice_deferred = models.BooleanField(default=False)
    privacy_notice_deferred_reason = models.CharField(max_length=180, blank=True)
    is_unknown = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patients_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="patients_updated",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    merged_into = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="merged_patients",
    )
    soft_deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["mobile", "full_name"]),
            models.Index(fields=["uhid"]),
            models.Index(fields=["old_file_number"]),
        ]
        permissions = [
            ("merge_patient", "Can merge duplicate patients"),
            ("view_patient_clinical_summary", "Can view patient clinical summary"),
        ]

    def __str__(self):
        return f"{self.full_name} ({self.uhid})"

    def clean(self):
        if not self.mobile and not self.no_phone:
            raise ValidationError({"mobile": "Mobile is required unless no-phone is checked."})
        if self.mobile and len(self.mobile) != 10:
            raise ValidationError({"mobile": "Mobile must be a 10-digit Indian number."})
        if not self.dob and self.age_years_at_registration is None:
            raise ValidationError("Enter either date of birth or age.")
        if (
            self.is_minor()
            and not self.is_unknown
            and not (self.guardian_name and self.guardian_relationship)
        ):
            raise ValidationError("Guardian name and relationship are required for minors.")
        if not self.privacy_notice_accepted and not self.privacy_notice_deferred:
            raise ValidationError(
                {"privacy_notice_accepted": "Privacy notice acceptance is required."}
            )

    def save(self, *args, **kwargs):
        if not self.uhid:
            self.uhid = generate_uhid()
        self.name_normalized = normalize_name(self.full_name)
        if self.privacy_notice_accepted and not self.privacy_notice_accepted_at:
            self.privacy_notice_accepted_at = timezone.now()
        if self.privacy_notice_accepted and not self.privacy_notice_version:
            self.privacy_notice_version = settings.HOSPITAL_PRIVACY_NOTICE_VERSION
        super().save(*args, **kwargs)

    def get_age_years(self, reference_date=None):
        reference_date = reference_date or timezone.localdate()
        if self.dob:
            years = reference_date.year - self.dob.year
            if (reference_date.month, reference_date.day) < (self.dob.month, self.dob.day):
                years -= 1
            return max(years, 0)
        return self.age_years_at_registration

    def is_minor(self):
        age = self.get_age_years()
        return age is not None and age < 18

    def soft_delete(self, by=None):
        self.is_active = False
        self.soft_deleted_at = timezone.now()
        fields = ["is_active", "soft_deleted_at", "updated_at"]
        if by is not None:
            self.updated_by = by
            fields.append("updated_by")
        self.save(update_fields=fields)


class PatientAllergy(models.Model):
    class Severity(models.TextChoices):
        MILD = "mild", "Mild"
        MODERATE = "moderate", "Moderate"
        SEVERE = "severe", "Severe"
        UNKNOWN = "unknown", "Unknown"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="allergies")
    substance = models.CharField(max_length=120)
    reaction = models.CharField(max_length=180, blank=True)
    severity = models.CharField(
        max_length=16, choices=Severity.choices, default=Severity.UNKNOWN
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["substance"]
        verbose_name_plural = "patient allergies"

    def __str__(self):
        return self.substance


class ChronicCondition(models.Model):
    patient = models.ForeignKey(
        Patient, on_delete=models.CASCADE, related_name="chronic_conditions"
    )
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


auditlog.register(Patient)
auditlog.register(PatientAllergy)
auditlog.register(ChronicCondition)
