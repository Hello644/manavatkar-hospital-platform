"""FastAPI face-recognition microservice for the attendance kiosk.

Runs in its own container (isolates the ~2 GB model footprint; can crash without
taking down OPD). Endpoints:
  GET  /health         liveness + whether the ML models are importable
  POST /embed {image}  detect + ArcFace embed one enrollment frame
  POST /match {image}  embed + brute-force cosine match over the enrolled gallery
"""

import db
import recognizer
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="facesvc", version="1.0")


class ImageIn(BaseModel):
    image: str


@app.get("/health")
def health():
    return {"status": "ok", "models_ready": recognizer.is_ready()}


@app.post("/embed")
def embed(payload: ImageIn):
    return recognizer.embed(payload.image)


@app.post("/match")
def match(payload: ImageIn):
    try:
        gallery = db.load_gallery()
    except Exception as exc:
        return {"ok": False, "error": f"gallery load failed: {exc}"}
    return recognizer.match(payload.image, gallery)
