from urllib.parse import quote

from django.utils import timezone

from .models import OutboundMessage


def normalize_msisdn(number):
    """Return a bare 10-digit Indian number, stripping +91/91/spaces."""
    digits = "".join(c for c in (number or "") if c.isdigit())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def whatsapp_link(number, text):
    msisdn = normalize_msisdn(number)
    return f"https://wa.me/91{msisdn}?text={quote(text)}"


def record_copy_text(rx, hospital):
    lines = [
        f"{hospital.name} — prescription record copy",
        f"Patient: {rx.patient.full_name} ({rx.patient.uhid})",
        f"Dr. {rx.doctor.display_name}, {rx.created_at:%d-%b-%Y}",
        "",
        "Record copy only — the signed printed original was issued to the patient.",
    ]
    return "\n".join(lines)


def log_message(*, patient, channel, to_number, body, purpose, status, user=None, error=""):
    return OutboundMessage.objects.create(
        patient=patient,
        channel=channel,
        to_number=normalize_msisdn(to_number),
        body=body,
        purpose=purpose,
        status=status,
        created_by=user,
        error=error,
        sent_at=timezone.now() if status == OutboundMessage.Status.SENT else None,
    )


def queue_message(*, patient, channel, to_number, body, purpose, user=None):
    """Queue a message for later delivery (reminders, confirmations). Stays
    QUEUED until a provider sends it — degrades silently offline."""
    return log_message(
        patient=patient, channel=channel, to_number=to_number, body=body,
        purpose=purpose, status=OutboundMessage.Status.QUEUED, user=user,
    )
