import re

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


PIN_RE = re.compile(r"^\d{6}$")


class User(AbstractUser):
    employee_code = models.CharField(max_length=24, unique=True, null=True, blank=True)
    mobile = models.CharField(max_length=15, blank=True)
    pin_hash = models.CharField(max_length=256, blank=True)
    pin_set_at = models.DateTimeField(null=True, blank=True)
    must_change_pin = models.BooleanField(default=False)

    def set_pin(self, raw_pin):
        if not PIN_RE.match(raw_pin or ""):
            raise ValidationError("PIN must be exactly 6 digits.")
        self.pin_hash = make_password(raw_pin)
        self.pin_set_at = timezone.now()
        self.must_change_pin = False

    def check_pin(self, raw_pin):
        if not self.pin_hash:
            return False
        return check_password(raw_pin, self.pin_hash)

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

