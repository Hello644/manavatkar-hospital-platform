import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models

from apps.patients.models import Patient


class OutboundMessage(models.Model):
    """A queued patient message (SMS / WhatsApp). Sending degrades silently
    offline: messages sit as QUEUED until a provider is reachable. WhatsApp
    record-copy shares are logged here too for the audit trail."""

    class Channel(models.TextChoices):
        SMS = "sms", "SMS"
        WHATSAPP = "whatsapp", "WhatsApp"

    class Purpose(models.TextChoices):
        RECORD_COPY = "record_copy", "Record copy"
        APPOINTMENT = "appointment", "Appointment"
        FOLLOWUP = "followup", "Follow-up"
        OTHER = "other", "Other"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        BLOCKED = "blocked", "Blocked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    patient = models.ForeignKey(
        Patient, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages"
    )
    channel = models.CharField(max_length=12, choices=Channel.choices)
    to_number = models.CharField(max_length=15)
    body = models.TextField()
    purpose = models.CharField(max_length=16, choices=Purpose.choices, default=Purpose.OTHER)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED)
    scheduled_for = models.DateField(null=True, blank=True)
    # Idempotency key so re-running reminders / re-booking never double-queues.
    reference = models.CharField(max_length=120, blank=True, db_index=True)
    error = models.CharField(max_length=240, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="messages_sent",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.get_channel_display()} to {self.to_number} ({self.status})"


auditlog.register(OutboundMessage)
