"""Host-based separation between the public website and the clinical system.

One server runs both. manwatkarhospital.in resolves to the hospital's public IP
and must reach *only* the marketing pages and the booking form; the clinical
app (patients, OPD, prescriptions, attendance, admin, login) is reachable only
from the hospital LAN.

Caddy enforces this first, with a path allowlist on the public site block. This
middleware is the backstop: if the reverse proxy is ever misconfigured, replaced
or bypassed, a request arriving on the public hostname still cannot reach a
patient record. Two independent layers, because the failure mode here is a
clinical data breach and a DPDP Act notification.

Fails closed: an unrecognised URL on the public host is refused, so a new app
added to config/urls.py is private until someone deliberately publishes it.
"""

from django.conf import settings
from django.http import Http404

# Telephony webhooks must be reachable from the internet or the AI phone
# receptionist cannot answer a call — the provider POSTs to them. They are
# allowed by (namespace, url_name), never by namespace: apps.voice also contains
# `call_log`, a staff page listing callers' phone numbers, which stays inside.
#
# Safe to expose because every one of these verifies an HMAC signature against
# TWILIO_AUTH_TOKEN and fails closed without it (apps.voice.views._verified),
# and settings.py refuses to boot with the agent enabled and no token set.
WEBHOOK_ROUTES = {
    ("voice", "incoming"),
    ("voice", "turn"),
    ("voice", "status_callback"),
}


class PublicSiteIsolationMiddleware:
    """404 anything that is not part of the public site when the request
    arrives on a public hostname."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        hosts = {h.lower() for h in getattr(settings, "PUBLIC_SITE_HOSTS", [])}
        if not hosts:
            return None  # no public hostname configured — LAN-only deployment
        host = request.get_host().split(":")[0].lower()
        if host not in hosts:
            return None  # LAN request: full clinical app

        resolver_match = request.resolver_match
        namespace = getattr(resolver_match, "namespace", None) if resolver_match else None
        url_name = getattr(resolver_match, "url_name", None) if resolver_match else None
        if namespace == "site":
            return None

        # Signed inbound webhooks, only while the feature that needs them is on.
        if (namespace, url_name) in WEBHOOK_ROUTES and settings.VOICE_AGENT_ENABLED:
            return None

        # Static and media are served by whitenoise/Caddy ahead of the URL
        # resolver, but allow them explicitly for the runserver case.
        if request.path.startswith((settings.STATIC_URL, "/static/")):
            return None

        # Everything else — /patients/, /opd/, /admin/, /login/, /voice/,
        # /attendance/ — does not exist as far as the internet is concerned.
        # 404 rather than 403: a 403 confirms there is something there.
        raise Http404("Not available on the public site.")
