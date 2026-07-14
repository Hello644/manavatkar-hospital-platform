import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models


class AiInteraction(models.Model):
    """Audit + record of an AI-assist call. Sending clinical context to an
    external model is a data-processing event — log that it happened, by whom,
    and keep the draft output for the doctor to reuse."""

    class Task(models.TextChoices):
        SUMMARY = "summary", "Record summary"
        SOAP = "soap", "SOAP draft"
        EXPLAIN = "explain", "Explain results"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    visit = models.ForeignKey(
        "opd.Visit", null=True, blank=True, on_delete=models.SET_NULL, related_name="ai_interactions"
    )
    task = models.CharField(max_length=12, choices=Task.choices)
    model = models.CharField(max_length=64, blank=True)
    output = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="ai_interactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_task_display()} · {self.created_at:%Y-%m-%d %H:%M}"


auditlog.register(AiInteraction)
