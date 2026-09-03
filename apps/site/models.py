from django.db import models
from django.utils import timezone


class Service(models.Model):
    """A department or service listed on the public website. Content lives in
    the DB so reception can add "Physiotherapy" without a deploy."""

    name = models.CharField(max_length=120)
    name_marathi = models.CharField("Name (Marathi)", max_length=120, blank=True)
    description = models.TextField(blank=True)
    # A short emoji or symbol shown as the card icon — avoids shipping an icon
    # font and keeps the page fast on a 3G phone.
    icon = models.CharField(
        max_length=8, blank=True, help_text="Optional emoji shown on the service card."
    )
    display_order = models.PositiveSmallIntegerField(default=100)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return self.name


class Announcement(models.Model):
    """Time-boxed notice on the home page — "Dr. Madhu on leave 12–15 Sept",
    a vaccination camp, revised timings. Expires on its own so a stale notice
    cannot sit on the site for months."""

    title = models.CharField(max_length=160)
    body = models.TextField(blank=True)
    starts_on = models.DateField(default=timezone.localdate)
    ends_on = models.DateField(
        null=True, blank=True, help_text="Leave blank to show until manually deactivated."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on"]

    def __str__(self):
        return self.title

    @classmethod
    def live(cls):
        today = timezone.localdate()
        return cls.objects.filter(
            is_active=True, starts_on__lte=today
        ).filter(models.Q(ends_on__isnull=True) | models.Q(ends_on__gte=today))


class PublicBookingAttempt(models.Model):
    """Rate-limit ledger and abuse trail for the unauthenticated booking form.

    The public form has no SMS OTP behind it, so this is what stops one person
    filling a doctor's whole day. It stores the source IP, which is personal
    data under the DPDP Act — hence the short retention enforced by
    ``manage.py purge_booking_attempts`` (see RETENTION_DAYS).
    """

    RETENTION_DAYS = 30

    class Outcome(models.TextChoices):
        BOOKED = "booked", "Booked"
        RATE_LIMITED = "rate_limited", "Rate limited"
        REJECTED = "rejected", "Rejected"
        SPAM = "spam", "Spam (honeypot)"

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    mobile = models.CharField(max_length=10, blank=True)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    detail = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["ip_address", "created_at"]),
            models.Index(fields=["mobile", "created_at"]),
        ]

    def __str__(self):
        return f"{self.created_at:%d-%b %H:%M} {self.outcome}"
