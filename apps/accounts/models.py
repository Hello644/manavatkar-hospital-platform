import re
from datetime import timedelta

from auditlog.registry import auditlog
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


PIN_RE = re.compile(r"^\d{6}$")

# A 6-digit PIN has only 10^6 combinations, so unlimited online guessing at a
# shared POS-style desk is a real lateral-privilege-escalation path. Lock the
# account for a cool-off window after a small number of consecutive failures.
PIN_MAX_FAILURES = 5
PIN_LOCKOUT_MINUTES = 5


class User(AbstractUser):
    employee_code = models.CharField(max_length=24, unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    pin_hash = models.CharField(max_length=256, blank=True)
    pin_set_at = models.DateTimeField(null=True, blank=True)
    must_change_pin = models.BooleanField(default=False)
    failed_pin_attempts = models.PositiveIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)

    def set_pin(self, raw_pin):
        if not PIN_RE.match(raw_pin or ""):
            raise ValidationError("PIN must be exactly 6 digits.")
        self.pin_hash = make_password(raw_pin)
        self.pin_set_at = timezone.now()
        self.must_change_pin = False
        self.failed_pin_attempts = 0
        self.pin_locked_until = None

    def check_pin(self, raw_pin):
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

    def is_pin_locked(self):
        return bool(self.pin_locked_until and self.pin_locked_until > timezone.now())

    def register_pin_failure(self):
        """Count a wrong PIN; lock the account once the threshold is reached."""
        self.failed_pin_attempts += 1
        fields = ["failed_pin_attempts"]
        if self.failed_pin_attempts >= PIN_MAX_FAILURES:
            self.pin_locked_until = timezone.now() + timedelta(minutes=PIN_LOCKOUT_MINUTES)
            self.failed_pin_attempts = 0
            fields.append("pin_locked_until")
        self.save(update_fields=fields)

    def reset_pin_failures(self):
        if self.failed_pin_attempts or self.pin_locked_until:
            self.failed_pin_attempts = 0
            self.pin_locked_until = None
            self.save(update_fields=["failed_pin_attempts", "pin_locked_until"])

    @property
    def role_names(self):
        return list(self.groups.order_by("name").values_list("name", flat=True))

    @property
    def primary_role(self):
        roles = self.role_names
        return roles[0] if roles else ""


class DoctorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="doctor_profile"
    )
    display_name = models.CharField(max_length=160)
    qualifications = models.CharField(max_length=160, blank=True)
    specialty = models.CharField(max_length=120, blank=True)
    state_medical_council = models.CharField(max_length=160, blank=True)
    registration_number = models.CharField(max_length=64, blank=True)
    hpr_id = models.CharField("HPR ID", max_length=64, blank=True)
    room_label = models.CharField(max_length=24, blank=True)
    consult_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    prescription_enabled = models.BooleanField(default=False)
    is_locum = models.BooleanField(default=False)
    valid_from = models.DateField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    # Public website (apps.site). Both default to False so adding a doctor never
    # publishes them by accident — listing a name and opening their calendar to
    # the internet are deliberate, separately revocable acts.
    show_on_website = models.BooleanField(
        "Show on public website",
        default=False,
        help_text="List this doctor on the public hospital website.",
    )
    accepts_online_booking = models.BooleanField(
        default=False,
        help_text="Let patients book this doctor's OPD slots from the website.",
    )
    public_bio = models.TextField(
        blank=True, help_text="Short paragraph shown on the public website."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_name"]

    def __str__(self):
        return self.display_name

    def clean(self):
        if self.prescription_enabled and not self.registration_number:
            raise ValidationError(
                {"registration_number": "Registration number is required for prescribing."}
            )
        if self.is_locum and (not self.valid_from or not self.valid_until):
            raise ValidationError("Locum doctors need both valid-from and valid-until dates.")
        if self.valid_from and self.valid_until and self.valid_until < self.valid_from:
            raise ValidationError({"valid_until": "Valid until cannot be before valid from."})
        if self.accepts_online_booking and not self.show_on_website:
            raise ValidationError(
                {"accepts_online_booking": (
                    "Online booking needs a public profile — tick 'Show on public "
                    "website' too, or patients cannot see who they are booking."
                )}
            )

    def can_prescribe_on(self, day=None):
        day = day or timezone.localdate()
        if not self.prescription_enabled or not self.registration_number:
            return False
        if self.is_locum:
            if self.valid_from and day < self.valid_from:
                return False
            if self.valid_until and day > self.valid_until:
                return False
        return True


# Audit account + prescriber-credential changes (PIN resets, activation, staff
# flags, registration number, prescribing enablement). Secrets are excluded so
# their hashes never land in the audit trail; the fact that they changed is
# still recorded via pin_set_at / last_login being present or the row's history.
auditlog.register(
    User,
    exclude_fields=["password", "pin_hash", "failed_pin_attempts", "pin_locked_until"],
)
auditlog.register(DoctorProfile)

