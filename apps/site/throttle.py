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

# ONE message for every refusal. Distinct messages would turn this open form
# into an oracle: type any mobile number, and the reply tells you whether that
# person has an upcoming appointment here. That is personal data about a third
# party handed to an anonymous stranger — a DPDP disclosure, and worse for a
# hospital, where "has an appointment" is itself sensitive. Staff still see the
# real reason in the PublicBookingAttempt log.
REFUSED = (
    "We could not complete this booking online. Please call the hospital "
    "and we will book it for you."
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
    """Return (public_message, internal_reason) if refused, else None.

    The caller shows the message and logs the reason; they are deliberately
    different — see REFUSED.
    """
    now = timezone.now()
    ip = client_ip(request)

    if ip:
        attempts = PublicBookingAttempt.objects.filter(ip_address=ip)
        if attempts.filter(created_at__gte=now - timedelta(hours=1)).count() >= IP_ATTEMPTS_PER_HOUR:
            return REFUSED, "ip hourly limit"
        if attempts.filter(created_at__gte=now - timedelta(days=1)).count() >= IP_ATTEMPTS_PER_DAY:
            return REFUSED, "ip daily limit"

    if mobile:
        booked_today = PublicBookingAttempt.objects.filter(
            mobile=mobile,
            outcome=PublicBookingAttempt.Outcome.BOOKED,
            created_at__gte=now - timedelta(days=1),
        ).count()
        if booked_today >= MOBILE_BOOKINGS_PER_DAY:
            return REFUSED, "mobile daily booking limit"

        open_appointments = Appointment.objects.filter(
            patient__mobile=mobile,
            date__gte=timezone.localdate(),
            status=Appointment.Status.BOOKED,
        ).count()
        if open_appointments >= MOBILE_OPEN_APPOINTMENTS:
            return REFUSED, "mobile open-appointment cap"
    return None
