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


def _booking_enabled():
    """False in the static export, which has no database to book into."""
    return getattr(settings, "PUBLIC_BOOKING_ENABLED", True)


def _public_doctors():
    return DoctorProfile.objects.filter(show_on_website=True).order_by("display_name")


def _base_context():
    return {
        "services": Service.objects.filter(is_active=True),
        "announcements": Announcement.live(),
        "doctors": _public_doctors(),
        # Generated from the booking engine, never hand-written: the board and
        # the bookable calendar are the same data.
        "timetable": booking.weekly_timetable(),
        "morning": booking.MORNING,
        "evening": booking.EVENING,
    }


def home(request):
    ctx = _base_context()
    ctx["booking_open"] = (
        _booking_enabled()
        and _public_doctors().filter(accepts_online_booking=True).exists()
    )
    ctx["page"] = "home"
    return render(request, "site/home.html", ctx)


def doctors(request):
    return render(request, "site/doctors.html", {**_base_context(), "page": "doctors"})


def services(request):
    return render(request, "site/services.html", {**_base_context(), "page": "services"})


def contact(request):
    return render(request, "site/contact.html", {**_base_context(), "page": "contact"})


def _session_options(doctor, on_date):
    """Sittings that run for this doctor/date, or [] if either is missing."""
    if doctor is None or on_date is None:
        return []
    result = booking.available_sessions(doctor.display_name, on_date.isoformat())
    return result["sessions"] if result.get("ok") else []


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
    if not _booking_enabled():
        return render(request, "site/book.html", {
            **_base_context(), "page": "book", "booking_offline": True,
        })
    today = timezone.localdate()
    limits = {
        "min_date": today.isoformat(),
        "max_date": (today + timedelta(days=booking.MAX_ADVANCE_DAYS)).isoformat(),
    }

    if request.method == "GET":
        doctor, on_date = _selected(request, request.GET)
        sessions = _session_options(doctor, on_date)
        form = AppointmentBookingForm(
            initial={"doctor": doctor.pk if doctor else None,
                     "date": on_date.isoformat() if on_date else ""},
            session_choices=sessions,
        )
        return render(request, "site/book.html", {
            **_base_context(), "page": "book", "form": form, "sessions": sessions,
            "picked": bool(doctor and on_date), **limits,
        })

    doctor, on_date = _selected(request, request.POST)
    sessions = _session_options(doctor, on_date)
    form = AppointmentBookingForm(request.POST, session_choices=sessions)

    # Honeypot first: never spend a DB write or a slot lookup on an obvious bot,
    # and never tell it why it failed.
    if form.is_spam():
        throttle.record(request, PublicBookingAttempt.Outcome.SPAM)
        return redirect("site:book_done")

    mobile = booking.normalise_mobile(request.POST.get("mobile"))
    blocked = throttle.check(request, mobile)
    if blocked:
        message, reason = blocked
        throttle.record(request, PublicBookingAttempt.Outcome.RATE_LIMITED, mobile, reason)
        messages.error(request, message)
        return render(request, "site/book.html", {
            **_base_context(), "page": "book", "form": form, "sessions": sessions, "picked": True, **limits,
        })

    if not form.is_valid():
        throttle.record(
            request, PublicBookingAttempt.Outcome.REJECTED, mobile, "form invalid"
        )
        return render(request, "site/book.html", {
            **_base_context(), "page": "book", "form": form, "sessions": sessions,
            "picked": bool(doctor and on_date), **limits,
        })

    data = form.cleaned_data
    result = booking.book_appointment(
        data["full_name"], data["mobile"], data["doctor"].display_name,
        data["date"].isoformat(), data["session"],
        source="website", reason=data.get("reason", ""),
    )
    if not result.get("ok"):
        throttle.record(
            request, PublicBookingAttempt.Outcome.REJECTED, mobile, result.get("error", "")
        )
        messages.error(request, result.get("error") or _(
            "We could not complete that booking. Please try another day."
        ))
        return render(request, "site/book.html", {
            **_base_context(), "page": "book", "form": form,
            "sessions": _session_options(doctor, on_date), "picked": True, **limits,
        })

    throttle.record(request, PublicBookingAttempt.Outcome.BOOKED, mobile)
    # Confirmation goes through the session, not the URL: a UUID in the address
    # bar would be a shareable link to someone's appointment details.
    sitting = result.get("session", {})
    request.session[CONFIRMATION_SESSION_KEY] = {
        "name": data["full_name"],
        "doctor": data["doctor"].display_name,
        "date": data["date"].isoformat(),
        "sitting": sitting.get("label", ""),
        "time": sitting.get("time", ""),
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
