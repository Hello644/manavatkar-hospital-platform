"""Client for the facesvc face-recognition microservice.

Kept behind this thin layer so the Django app never imports the ML stack. If the
service is unconfigured or unreachable, calls fail soft — the kiosk falls back to
PIN, and enrollment reports the service is unavailable."""

import json
from urllib import error, request

from django.conf import settings


def is_configured():
    return bool(settings.FACE_SERVICE_URL)


def _post(path, payload, timeout=10):
    url = settings.FACE_SERVICE_URL.rstrip("/") + path
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def embed(image_b64):
    """Return {ok, embedding, quality, liveness} for an enrollment frame."""
    if not is_configured():
        return {"ok": False, "error": "Face service not configured"}
    try:
        return _post("/embed", {"image": image_b64})
    except (error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"Face service unreachable: {exc}"}


def match(image_b64):
    """Return {ok, staff_id, confidence, margin, liveness} for a punch frame.
    The service does brute-force cosine matching over stored embeddings."""
    if not is_configured():
        return {"ok": False, "error": "Face service not configured"}
    try:
        return _post("/match", {"image": image_b64})
    except (error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "error": f"Face service unreachable: {exc}"}
