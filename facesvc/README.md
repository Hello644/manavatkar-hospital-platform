# facesvc — face-recognition microservice

Isolated FastAPI service for the attendance kiosk (PLAN §6). Runs in its own
container so the ~2 GB model footprint can't take down OPD.

- **Detection + recognition:** InsightFace `buffalo_l` (SCRFD-500MF + ArcFace,
  512-d embeddings) via ONNX Runtime, CPU-only.
- **Matching:** brute-force cosine over the enrolled gallery read from Postgres
  (`attendance_faceenrollment`). No vector DB — fine for ~1,800 vectors.
- **Liveness:** `passive_liveness()` is a stub returning 1.0. Drop in the
  MiniFASNet Silent-Face ONNX model to score the aligned crop. Per PLAN, the real
  deterrent at this scale is the stored photo + visible mounting + policy.

## Endpoints
- `GET /health` → `{status, models_ready}`
- `POST /embed {image}` → `{ok, embedding, quality, liveness}` (enrollment)
- `POST /match {image}` → `{ok, staff_id, confidence, margin, liveness}` (punch)

The Django side (`apps/attendance`) applies the accept thresholds
(`FACE_MATCH_THRESHOLD` 0.42 + `FACE_MARGIN_THRESHOLD` 0.08) and stores the punch.

## Run
Via `docker compose up facesvc` (the compose file wires `DATABASE_URL` and a
`face_models` volume). `buffalo_l` (~300 MB) auto-downloads into
`/root/.insightface` on the first request. Set `FACE_SERVICE_URL=http://facesvc:8080`
and `KIOSK_DEVICE_TOKEN` in `.env` to activate the kiosk face path; without them
the kiosk falls back to PIN.

## Not verifiable in CI
This service needs the ML models and real face images; it is not covered by the
Django test suite. Validate on the target hardware during Phase-3 threshold
tuning (PLAN §12).
