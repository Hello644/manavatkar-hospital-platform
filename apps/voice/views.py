from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.accounts.permissions import ATTENDANCE_VIEW_ROLES, role_required

from . import agent, telephony
from .models import CallSession

XML = "application/xml"


def _voice():
    return settings.VOICE_TTS_VOICE, settings.VOICE_TTS_LANGUAGE


def _verified(request):
    """Verify the request came from Twilio (skipped if no auth token set)."""
    token = settings.TWILIO_AUTH_TOKEN
    if not token:
        return True
    url = request.build_absolute_uri()
    params = {k: request.POST[k] for k in request.POST}
    signature = request.headers.get("X-Twilio-Signature", "")
    return telephony.valid_signature(token, url, params, signature)


@csrf_exempt
@require_POST
def incoming(request):
    if not _verified(request):
        return HttpResponse(status=403)
    voice, lang = _voice()
    call_sid = request.POST.get("CallSid", "")
    session, _created = CallSession.objects.get_or_create(
        call_sid=call_sid,
        defaults={
            "from_number": request.POST.get("From", ""),
            "to_number": request.POST.get("To", ""),
            "language": lang,
        },
    )
    if not agent.is_available():
        session.status = CallSession.Status.NO_AGENT
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at"])
        return HttpResponse(
            telephony.say_hangup(
                "Sorry, our booking assistant is not available right now. "
                "Please call again later or visit the reception. Goodbye.",
                voice, lang,
            ),
            content_type=XML,
        )
    from apps.core.models import HospitalProfile

    greeting = (
        f"Thank you for calling {HospitalProfile.get_solo().name}. "
        "I can help you book an appointment. How can I help?"
    )
    turn_url = request.build_absolute_uri(reverse("voice:turn"))
    return HttpResponse(telephony.gather(greeting, turn_url, voice, lang), content_type=XML)


@csrf_exempt
@require_POST
def turn(request):
    if not _verified(request):
        return HttpResponse(status=403)
    voice, lang = _voice()
    call_sid = request.POST.get("CallSid", "")
    session = CallSession.objects.filter(call_sid=call_sid).first()
    if session is None:
        return HttpResponse(
            telephony.say_hangup("Sorry, something went wrong. Goodbye.", voice, lang),
            content_type=XML,
        )

    speech = (request.POST.get("SpeechResult") or "").strip()
    turn_url = request.build_absolute_uri(reverse("voice:turn"))

    if not speech:
        return HttpResponse(
            telephony.gather("Sorry, I didn't catch that. Could you repeat?", turn_url, voice, lang),
            content_type=XML,
        )

    reply, done = agent.respond(session, speech)

    if done or session.turns >= settings.VOICE_MAX_TURNS:
        session.status = CallSession.Status.COMPLETED
        session.ended_at = timezone.now()
        session.save(update_fields=["status", "ended_at"])
        return HttpResponse(telephony.say_hangup(reply, voice, lang), content_type=XML)

    return HttpResponse(telephony.gather(reply, turn_url, voice, lang), content_type=XML)


@csrf_exempt
@require_POST
def status_callback(request):
    call_sid = request.POST.get("CallSid", "")
    call_status = request.POST.get("CallStatus", "")
    if call_status in ("completed", "failed", "busy", "no-answer"):
        session = CallSession.objects.filter(call_sid=call_sid, ended_at__isnull=True).first()
        if session:
            session.ended_at = timezone.now()
            if session.status == CallSession.Status.ACTIVE:
                session.status = (
                    CallSession.Status.COMPLETED if call_status == "completed"
                    else CallSession.Status.FAILED
                )
            session.save(update_fields=["status", "ended_at"])
    return HttpResponse(status=204)


@role_required(*ATTENDANCE_VIEW_ROLES)
def call_log(request):
    sessions = CallSession.objects.select_related("booked_appointment__doctor", "patient")[:100]
    return render(request, "voice/call_log.html", {"sessions": sessions})
