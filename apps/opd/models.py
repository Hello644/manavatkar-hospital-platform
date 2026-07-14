import uuid
from decimal import Decimal

from auditlog.registry import auditlog
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient


# Queue order is (-priority, skip_count, registered_at): an emergency always
# comes first (patient safety), then a resumed hold returns to the front of the
# ordinary queue, then appointments beat walk-ins, and a skipped patient falls
# behind unskipped patients of the same priority.
PRIORITY_WALK_IN = 0
PRIORITY_APPOINTMENT = 1
PRIORITY_RESUMED = 2
PRIORITY_EMERGENCY = 3


class TokenSequence(models.Model):
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.CASCADE, related_name="token_sequences"
    )
    date = models.DateField()
    last_value = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["doctor", "date"], name="uniq_token_seq_doctor_date")
        ]

    def __str__(self):
        return f"{self.doctor} {self.date}: {self.last_value}"


class Visit(models.Model):
    class Source(models.TextChoices):
        WALK_IN = "walk_in", "Walk-in"
        APPOINTMENT = "appointment", "Appointment"

    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        VITALS_DONE = "vitals_done", "Vitals done"
        IN_CONSULT = "in_consult", "In consult"
        ON_HOLD = "on_hold", "On hold"
        PARKED = "parked", "Parked"
        COMPLETED = "completed", "Completed"
        NO_SHOW = "no_show", "No show"

    class Disposition(models.TextChoices):
        HOME = "home", "Home"
        FOLLOW_UP = "follow_up", "Follow-up"
        ADMIT_ADVISED = "admit_advised", "Admission advised"
        REFERRED = "referred", "Referred out"
        EXPIRED = "expired", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="visits")
    doctor = models.ForeignKey(DoctorProfile, on_delete=models.PROTECT, related_name="visits")
    visit_date = models.DateField(default=timezone.localdate, db_index=True)
    token_number = models.PositiveSmallIntegerField()
    token_label = models.CharField(max_length=12)
    source = models.CharField(max_length=16, choices=Source.choices, default=Source.WALK_IN)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.WAITING, db_index=True
    )
    is_emergency = models.BooleanField(default=False)
    priority = models.PositiveSmallIntegerField(default=PRIORITY_WALK_IN)
    skip_count = models.PositiveSmallIntegerField(default=0)

    is_mlc = models.BooleanField("Medico-legal case", default=False)
    mlc_brought_by = models.CharField(max_length=180, blank=True)
    mlc_police_station = models.CharField(max_length=180, blank=True)
    mlc_notes = models.TextField(blank=True)

    disposition = models.CharField(max_length=16, choices=Disposition.choices, blank=True)
    disposition_note = models.CharField(max_length=240, blank=True)
    followup_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Denormalized (visit_date + followup_days) so the front-desk "due" call list
    # can query it directly. Also the value that prints as a follow-up chip.
    followup_date = models.DateField(null=True, blank=True, db_index=True)
    referred_to = models.CharField(max_length=180, blank=True)

    registered_at = models.DateTimeField(auto_now_add=True)
    vitals_at = models.DateTimeField(null=True, blank=True)
    called_at = models.DateTimeField(null=True, blank=True)
    consult_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="visits_created",
    )

    class Meta:
        ordering = ["-registered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "visit_date", "token_number"],
                name="uniq_token_doctor_date",
            ),
            # A doctor can have at most one patient in consult at a time. Backs up
            # the row-locked guard in services.call_next/start_consult.
            models.UniqueConstraint(
                fields=["doctor", "visit_date"],
                condition=models.Q(status="in_consult"),
                name="uniq_one_in_consult_per_doctor_day",
            ),
        ]
        indexes = [models.Index(fields=["visit_date", "status"])]

    def __str__(self):
        return f"{self.token_label} · {self.patient.full_name} · {self.visit_date}"

    def clean(self):
        if self.status == self.Status.COMPLETED and not self.disposition:
            raise ValidationError({"disposition": "Disposition is required to complete a visit."})
        if self.disposition == self.Disposition.REFERRED and not self.referred_to:
            raise ValidationError({"referred_to": "Enter where the patient was referred."})
        if self.is_mlc and not (self.mlc_brought_by or self.mlc_police_station or self.mlc_notes):
            raise ValidationError(
                {"mlc_notes": "Record who brought the patient or the police station for an MLC."}
            )

    def save(self, *args, **kwargs):
        if self.is_emergency:
            self.priority = max(self.priority, PRIORITY_EMERGENCY)
        super().save(*args, **kwargs)

    @property
    def is_in_queue(self):
        return self.status in {self.Status.WAITING, self.Status.VITALS_DONE}

    @property
    def paid_amount(self):
        total = self.receipts.filter(is_refunded=False).aggregate(total=models.Sum("amount"))
        return total["total"] or Decimal("0")


class VitalsRecord(models.Model):
    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="vitals")
    weight_kg = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("300"))],
    )
    height_cm = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("30")), MaxValueValidator(Decimal("250"))],
    )
    bp_systolic = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(300)]
    )
    bp_diastolic = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(200)]
    )
    pulse = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(300)]
    )
    spo2 = models.PositiveSmallIntegerField(
        "SpO2 %", null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(100)]
    )
    temp_f = models.DecimalField(
        "Temperature °F",
        max_digits=4,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("90")), MaxValueValidator(Decimal("110"))],
    )
    rbs = models.PositiveSmallIntegerField(
        "RBS mg/dL", null=True, blank=True, validators=[MinValueValidator(20), MaxValueValidator(900)]
    )
    pain_score = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(10)]
    )
    lmp_date = models.DateField("LMP", null=True, blank=True)
    chief_complaint = models.CharField(max_length=240, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vitals_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "vitals records"

    def __str__(self):
        return f"Vitals for {self.visit.token_label}"

    @property
    def bmi(self):
        if not self.weight_kg or not self.height_cm:
            return None
        meters = Decimal(self.height_cm) / Decimal("100")
        return round(Decimal(self.weight_kg) / (meters * meters), 1)

    @property
    def flags(self):
        notes = []
        if self.spo2 is not None and self.spo2 < 94:
            notes.append("Low SpO2")
        if self.bp_systolic is not None and self.bp_systolic > 160:
            notes.append("High BP")
        elif self.bp_diastolic is not None and self.bp_diastolic > 100:
            notes.append("High BP")
        if self.temp_f is not None and self.temp_f >= Decimal("100.4"):
            notes.append("Fever")
        return notes


class Appointment(models.Model):
    class Status(models.TextChoices):
        BOOKED = "booked", "Booked"
        CHECKED_IN = "checked_in", "Checked in"
        NO_SHOW = "no_show", "No show"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="appointments")
    doctor = models.ForeignKey(
        DoctorProfile, on_delete=models.PROTECT, related_name="appointments"
    )
    date = models.DateField(db_index=True)
    slot_time = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField(default=10)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BOOKED)
    notes = models.CharField(max_length=240, blank=True)
    cancelled_reason = models.CharField(max_length=240, blank=True)
    visit = models.OneToOneField(
        Visit, null=True, blank=True, on_delete=models.SET_NULL, related_name="appointment"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="appointments_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "slot_time"]
        indexes = [models.Index(fields=["doctor", "date"])]

    def __str__(self):
        return f"{self.patient.full_name} · {self.doctor} · {self.date} {self.slot_time}"


class ReceiptSequence(models.Model):
    year = models.PositiveSmallIntegerField(unique=True)
    last_value = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.year}: {self.last_value}"


class Receipt(models.Model):
    class Mode(models.TextChoices):
        CASH = "cash", "Cash"
        UPI = "upi", "UPI"

    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="receipts")
    receipt_no = models.CharField(max_length=20, unique=True, editable=False)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.CASH)
    is_refunded = models.BooleanField(default=False)
    refund_reason = models.CharField(max_length=240, blank=True)
    refunded_at = models.DateTimeField(null=True, blank=True)
    refunded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receipts_refunded",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="receipts_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.receipt_no} · ₹{self.amount}"


class ConsultationNote(models.Model):
    """The doctor's structured clinical note for a visit (SOAP-style). Separate
    from nurse-entered vitals; one per visit."""

    visit = models.OneToOneField(Visit, on_delete=models.CASCADE, related_name="note")
    chief_complaint = models.CharField(max_length=240, blank=True)
    history = models.TextField("History of present illness", blank=True)
    examination = models.TextField("Examination / findings", blank=True)
    diagnosis = models.CharField(max_length=240, blank=True)
    assessment = models.TextField(blank=True)
    plan = models.TextField("Plan / treatment", blank=True)
    advice = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="notes_recorded",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Note for {self.visit.token_label}"

    @property
    def is_empty(self):
        return not any(
            [self.chief_complaint, self.history, self.examination, self.diagnosis,
             self.assessment, self.plan, self.advice]
        )


class Teleconsult(models.Model):
    """A video consultation room (Jitsi Meet) for a visit. No account needed —
    the patient opens the room URL on their phone."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        ENDED = "ended", "Ended"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.OneToOneField(
        Visit, on_delete=models.CASCADE, related_name="teleconsult"
    )
    room_name = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="teleconsults_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Teleconsult {self.room_name}"


auditlog.register(Visit)
auditlog.register(VitalsRecord)
auditlog.register(ConsultationNote)
auditlog.register(Appointment)
auditlog.register(Receipt)
auditlog.register(Teleconsult)
