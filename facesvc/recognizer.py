"""Face detection + embedding + (passive) liveness.

Detection + ArcFace recognition come from InsightFace `buffalo_l` (SCRFD +
ArcFace, ONNX Runtime, CPU). Matching is brute-force cosine over the enrolled
gallery loaded from Postgres — no vector DB (~1,800 vectors is fine in-process).

Everything is loaded lazily and guarded: if the ML stack or models are missing,
calls return {"ok": False, ...} so the kiosk falls back to PIN rather than 500.
"""

import base64

_app = None


def is_ready():
    try:
        import insightface  # noqa: F401
        return True
    except Exception:
        return False


def _get_app():
    global _app
    if _app is not None:
        return _app
    from insightface.app import FaceAnalysis

    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    _app = app
    return app


def _decode(image_b64):
    import cv2
    import numpy as np

    _, _, data = image_b64.partition(",")
    raw = base64.b64decode(data or image_b64)
    arr = np.frombuffer(raw, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def passive_liveness(img, face):
    """Placeholder for MiniFASNet Silent-Face passive anti-spoofing.

    Per PLAN §6 the real deterrent at this scale is the stored photo + visible
    mounting + policy, not a spoof-proof classifier. Drop the MiniFASNet ONNX
    model in and score the aligned crop here; until then this passes (1.0) and
    every punch still stores a photo for audit.
    """
    return 1.0


def embed(image_b64):
    try:
        app = _get_app()
        img = _decode(image_b64)
        if img is None:
            return {"ok": False, "error": "Could not decode image"}
        faces = app.get(img)
        if not faces:
            return {"ok": False, "error": "No face detected"}
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return {
            "ok": True,
            "embedding": [float(x) for x in face.normed_embedding],
            "quality": float(face.det_score),
            "liveness": passive_liveness(img, face),
        }
    except Exception as exc:  # ML stack / model missing → fail soft
        return {"ok": False, "error": f"embed failed: {exc}"}


def _cosine(a, b):
    import numpy as np

    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = np.linalg.norm(a) * np.linalg.norm(b) + 1e-9
    return float(np.dot(a, b) / denom)


def match(image_b64, gallery):
    """gallery: list of {"staff_id", "embedding"}. Returns top-1 id, cosine
    confidence, and top1−top2 margin (the sibling/lookalike guard)."""
    probe = embed(image_b64)
    if not probe.get("ok"):
        return probe
    best = {}
    for item in gallery:
        score = _cosine(probe["embedding"], item["embedding"])
        sid = item["staff_id"]
        if score > best.get(sid, -1.0):
            best[sid] = score
    if not best:
        return {"ok": True, "staff_id": None, "confidence": 0.0, "margin": 0.0, "liveness": probe["liveness"]}
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    top1_id, top1 = ranked[0]
    top2 = ranked[1][1] if len(ranked) > 1 else 0.0
    return {
        "ok": True,
        "staff_id": top1_id,
        "confidence": top1,
        "margin": top1 - top2,
        "liveness": probe["liveness"],
    }
