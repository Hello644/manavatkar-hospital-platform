"""Abuse controls for the unauthenticated public booking form.

There is no SMS OTP in front of this form (no gateway is provisioned — see
ops/deployment/go-live-manwatkarhospital.md), so these limits are the only thing
between the internet and a doctor's calendar. They are deliberately DB-backed
rather than cache-backed: gunicorn runs several workers and a per-process
LocMemCache would let each worker grant the full quota.
"""

from datetime import timedelta

from django.utils import timezone

from apps.opd.models import Appointment

from .models import PublicBookingAttempt

# Attempts (of any outcome) allowed from one IP.
IP_ATTEMPTS_PER_HOUR = 8
IP_ATTEMPTS_PER_DAY = 20
# Successful bookings allowed against one mobile number.
MOBILE_BOOKINGS_PER_DAY = 3
# Upcoming unattended appointments one mobile may hold at once. Stops a single
# number from silently reserving a week of slots.
MOBILE_OPEN_APPOINTMENTS = 2

TOO_MANY = (
    "Too many booking attempts from this device. Please try again later, "
    "or call the hospital and we will book it for you."
)


def client_ip(request):
    """Trust X-Forwarded-For only for its LAST hop, which is what our own Caddy
    appends. Earlier entries are client-supplied and forgeable."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR") or None


def record(request, outcome, mobile="", detail=""):
    PublicBookingAttempt.objects.create(
        ip_address=client_ip(request),
        mobile=(mobile or "")[:10],
        outcome=outcome,
        detail=detail[:200],
    )


def check(request, mobile):
    """Return an error string if this request should be refused, else None."""
    now = timezone.now()
    ip = client_ip(request)

    if ip:
        attempts = PublicBookingAttempt.objects.filter(ip_address=ip)
        if attempts.filter(created_at__gte=now - timedelta(hours=1)).count() >= IP_ATTEMPTS_PER_HOUR:
            return TOO_MANY
        if attempts.filter(created_at__gte=now - timedelta(days=1)).count() >= IP_ATTEMPTS_PER_DAY:
            return TOO_MANY

    if mobile:
        booked_today = PublicBookingAttempt.objects.filter(
            mobile=mobile,
            outcome=PublicBookingAttempt.Outcome.BOOKED,
            created_at__gte=now - timedelta(days=1),
        ).count()
        if booked_today >= MOBILE_BOOKINGS_PER_DAY:
            return (
                "This number has already booked today. Please call the hospital "
                "if you need another appointment."
            )

        open_appointments = Appointment.objects.filter(
            patient__mobile=mobile,
            date__gte=timezone.localdate(),
            status=Appointment.Status.BOOKED,
        ).count()
        if open_appointments >= MOBILE_OPEN_APPOINTMENTS:
            return (
                "This number already has upcoming appointments with us. "
                "Please call the hospital to add another."
            )
    return None
