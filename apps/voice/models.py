import uuid

from auditlog.registry import auditlog
from django.db import models


class CallSession(models.Model):
    """State for one inbound call, persisted across telephony webhook turns
    (each caller utterance is a separate HTTP request)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        NO_AGENT = "no_agent", "Agent unavailable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call_sid = models.CharField(max_length=64, unique=True, db_index=True)
    from_number = models.CharField(max_length=32, blank=True)
    to_number = models.CharField(max_length=32, blank=True)
    language = models.CharField(max_length=12, default="en-IN")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    # The Anthropic messages array (list of role/content dicts) — the running
    # transcript + tool exchanges for the tool-use loop.
    messages = models.JSONField(default=list, blank=True)
    turns = models.PositiveSmallIntegerField(default=0)
    patient = models.ForeignKey(
        "patients.Patient", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="voice_calls",
    )
    booked_appointment = models.ForeignKey(
        "opd.Appointment", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="voice_calls",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Call {self.call_sid} from {self.from_number} ({self.status})"

    @property
    def spoken_transcript(self):
        """Human-readable transcript (text turns only) for the call log UI."""
        lines = []
        for msg in self.messages:
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, str):
                text = content
            else:
                text = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            if text.strip() and role in ("user", "assistant"):
                lines.append((role, text.strip()))
        return lines


auditlog.register(CallSession)
