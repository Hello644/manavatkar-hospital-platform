"""Public website views for manwatkarhospital.in.

Everything here is unauthenticated and internet-facing. Two rules hold:
  1. No view may read patient data. The booking flow writes an appointment and
     reads back only what the visitor themselves just typed.
  2. Nothing here may leak whether a mobile number is already a patient — that
     would turn the form into a "does X attend this hospital?" oracle.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from apps.accounts.models import DoctorProfile
from apps.opd import booking

from . import throttle
from .forms import AppointmentBookingForm
from .models import Announcement, PublicBookingAttempt, Service

CONFIRMATION_SESSION_KEY = "public_booking_confirmation"


def _public_doctors():
    return DoctorProfile.objects.filter(show_on_website=True).order_by("display_name")


def _base_context():
    return {
        "services": Service.objects.filter(is_active=True),
        "announcements": Announcement.live(),
        "doctors": _public_doctors(),
    }


def home(request):
    ctx = _base_context()
    ctx["booking_open"] = _public_doctors().filter(accepts_online_booking=True).exists()
    return render(request, "site/home.html", ctx)


def doctors(request):
    return render(request, "site/doctors.html", _base_context())


def services(request):
    return render(request, "site/services.html", _base_context())


def contact(request):
    return render(request, "site/contact.html", _base_context())


def _slot_options(doctor, on_date):
    """Free times for this doctor/date, or [] if either is missing or invalid."""
    if doctor is None or on_date is None:
        return []
    result = booking.available_slots(doctor.display_name, on_date.isoformat(), limit=200)
    return result["slots"] if result.get("ok") else []


def _selected(request, data):
    """Resolve the doctor and date the visitor has chosen so far, from either
    the GET query (slot refresh) or the POST body (submission)."""
    doctor = None
    doctor_pk = data.get("doctor")
    if doctor_pk:
        doctor = DoctorProfile.objects.filter(
            pk=doctor_pk, accepts_online_booking=True, show_on_website=True
        ).first()
    on_date = booking.parse_date(data.get("date"))
    return doctor, on_date


@require_http_methods(["GET", "POST"])
def book(request):
    today = timezone.localdate()
    limits = {
        "min_date": today.isoformat(),
        "max_date": (today + timedelta(days=booking.MAX_ADVANCE_DAYS)).isoformat(),
    }

    if request.method == "GET":
        doctor, on_date = _selected(request, request.GET)
        slots = _slot_options(doctor, on_date)
        form = AppointmentBookingForm(
            initial={"doctor": doctor.pk if doctor else None,
                     "date": on_date.isoformat() if on_date else ""},
            slot_choices=slots,
        )
        return render(request, "site/book.html", {
            **_base_context(), "form": form, "slots": slots,
            "picked": bool(doctor and on_date), **limits,
        })

    doctor, on_date = _selected(request, request.POST)
    slots = _slot_options(doctor, on_date)
    form = AppointmentBookingForm(request.POST, slot_choices=slots)

    # Honeypot first: never spend a DB write or a slot lookup on an obvious bot,
    # and never tell it why it failed.
    if form.is_spam():
        throttle.record(request, PublicBookingAttempt.Outcome.SPAM)
        return redirect("site:book_done")

    mobile = booking.normalise_mobile(request.POST.get("mobile"))
    blocked = throttle.check(request, mobile)
    if blocked:
        throttle.record(request, PublicBookingAttempt.Outcome.RATE_LIMITED, mobile, blocked)
        messages.error(request, blocked)
        return render(request, "site/book.html", {
            **_base_context(), "form": form, "slots": slots, "picked": True, **limits,
        })

    if not form.is_valid():
        throttle.record(
            request, PublicBookingAttempt.Outcome.REJECTED, mobile, "form invalid"
        )
        return render(request, "site/book.html", {
            **_base_context(), "form": form, "slots": slots,
            "picked": bool(doctor and on_date), **limits,
        })

    data = form.cleaned_data
    result = booking.book_appointment(
        data["full_name"], data["mobile"], data["doctor"].display_name,
        data["date"].isoformat(), data["slot_time"],
        source="website", reason=data.get("reason", ""),
    )
    if not result.get("ok"):
        throttle.record(
            request, PublicBookingAttempt.Outcome.REJECTED, mobile, result.get("error", "")
        )
        messages.error(request, _(
            "That time was just taken. Please pick another one."
        ))
        return render(request, "site/book.html", {
            **_base_context(), "form": form,
            "slots": _slot_options(doctor, on_date), "picked": True, **limits,
        })

    throttle.record(request, PublicBookingAttempt.Outcome.BOOKED, mobile)
    # Confirmation goes through the session, not the URL: a UUID in the address
    # bar would be a shareable link to someone's appointment details.
    request.session[CONFIRMATION_SESSION_KEY] = {
        "name": data["full_name"],
        "doctor": data["doctor"].display_name,
        "date": data["date"].isoformat(),
        "time": data["slot_time"],
        "fee": str(data["doctor"].consult_fee),
    }
    return redirect("site:book_done")


def book_done(request):
    confirmation = request.session.pop(CONFIRMATION_SESSION_KEY, None)
    return render(request, "site/book_done.html", {
        **_base_context(), "confirmation": confirmation,
    })


def robots(request):
    """Allow the marketing pages, keep the booking form out of the index."""
    from django.http import HttpResponse

    body = "\n".join([
        "User-agent: *",
        "Disallow: /book/",
        "Allow: /",
        f"Sitemap: https://{settings.PUBLIC_SITE_HOSTS[0]}/sitemap.xml"
        if settings.PUBLIC_SITE_HOSTS else "",
        "",
    ])
    return HttpResponse(body, content_type="text/plain")


def sitemap(request):
    from django.http import HttpResponse

    host = request.get_host()
    paths = [reverse("site:home"), reverse("site:doctors"),
             reverse("site:services"), reverse("site:contact")]
    urls = "".join(f"<url><loc>https://{host}{p}</loc></url>" for p in paths)
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return HttpResponse(body, content_type="application/xml")
