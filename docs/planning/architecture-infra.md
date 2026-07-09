# Technical Architecture & Infrastructure

## 1. Stack

**Backend options compared:**

| Option | Pros | Cons |
|---|---|---|
| **Django 5.x (Python)** | Batteries included: auth/sessions/permissions, admin UI (free CRUD for masters like drug list, staff, shifts), ORM + migrations, `django-auditlog`, mature printing/PDF ecosystem (WeasyPrint). Python shares language with the face-recognition service. Huge Indian hiring pool. | Slower raw throughput (irrelevant at <50 concurrent users); "boring". |
| FastAPI (Python) | Async, clean APIs, great for the face service. | No admin, no auth/permissions framework, no migrations story — you rebuild Django's free parts by hand; bad trade for 1-2 devs. |
| NestJS (Node) + React | Single language front/back, good websockets. | Heavier boilerplate, ORM (Prisma/TypeORM) migration ergonomics weaker, face-rec ecosystem is Python-first, splits the team across two runtimes anyway. |

**Recommendation: Django 5.x monolith + HTMX/Alpine.js for interactivity, with FastAPI only for the isolated face-recognition microservice.** Server-rendered pages are the right call for LAN apps on cheap hospital PCs: no SPA build pipeline, no API-versioning overhead, instant back-button/print behavior. Use HTMX for the live queue board and dashboards (poll or SSE every 3-5 s); one small React/vanilla page is acceptable for the waiting-room token TV display if needed. Django REST Framework only for the kiosk endpoints (~4 endpoints).

**Database: PostgreSQL 16** — confirmed, no argument. Add `pgvector` extension for face embeddings (keeps embeddings transactionally consistent with staff records; no separate vector DB). Redis optional in v1 — Django DB-backed sessions and HTMX polling are enough; add Redis only if/when moving queue updates to websockets.

Key data entities to lock early (shared registry requirement): `Patient` (UHID auto-generated e.g. `HSP-2026-000123`, name, age/DOB, sex, phone, address, ABHA ID nullable for future ABDM), `Visit` (patient FK, doctor FK, token_no, department, status enum: registered/waiting/in-consult/done, vitals JSON), `Prescription` (visit FK, doctor FK, Rx lines: drug FK, dose, frequency, duration, instructions; diagnosis, advice, follow-up date), `Drug` master, `Staff` (role, shift assignment, face embeddings 1-N), `AttendanceEvent` (staff FK, timestamp, direction in/out, confidence score, photo path, device_id, sync_status).

## 2. Kiosk client

| Option | Camera control | Offline | Lockdown | Effort |
|---|---|---|---|---|
| Native Android (Kotlin + CameraX) | Full (exposure, focus, torch) | Best (Room DB queue) | Via Device Owner / MDM | High — needs an Android dev, Play/APK sideload maintenance |
| **PWA in Fully Kiosk Browser** | getUserMedia is adequate for face capture; Fully adds motion-detection wake, screen-on control | IndexedDB queue + service worker | Fully Kiosk handles pinning, auto-restart, remote REST admin, boot-on-power | Low — pure web skills |
| Plain Chrome kiosk / screen pinning | Same camera API | Same | Weak — escapable, no watchdog, no auto-relaunch on crash | Low |

**Recommendation: PWA running inside Fully Kiosk Browser (₹700-800 one-time per device).** The team is web devs; Fully Kiosk gives 90% of native lockdown (single-app pinning, crash auto-restart, scheduled reboot 4 a.m., remote screenshot/health via its REST API, screensaver with motion wake) for near-zero effort. Flow: motion wakes screen → live camera preview → capture frame on face detected client-side (use `FaceDetector` API or tiny BlazeFace TF.js model just for "is there a face", not recognition) → POST JPEG to server → server responds with name + IN/OUT + green/red toast in <1.5 s.

Critical detail: **getUserMedia requires HTTPS** — this forces the TLS decision in §5. Hardware: any 10" Android tablet (Samsung Galaxy Tab A9 / Lenovo Tab M10, ₹12-16k) wall-mounted at eye height with a locking mount (₹2-3k), permanently powered (hide cable in conduit), front camera at 1.5-1.6 m height, avoid backlighting from the entrance door — add a small LED strip above the tablet if the entrance is dark.

## 3. Face-recognition service placement & sizing

**Separate containerized FastAPI service** (not in-process in Django): isolates the ~1.5-2 GB model memory footprint, lets it crash/restart without taking down OPD, and pins its CPU usage. Django calls it over localhost HTTP; embeddings and match decisions persist via Django.

**Pipeline (all open-source, CPU-only):**
- Detection + alignment + embedding: **InsightFace `buffalo_l`** (SCRFD-10G detector + ArcFace-R100 512-d embedding) via **ONNX Runtime** CPU. Alternative packaged option: **CompreFace** (Exadel, self-hosted Docker, has admin UI) — good if you want zero ML code, but it's a heavier Java/multi-container stack; the InsightFace wrapper is ~200 lines and you control it. Avoid dlib/`face_recognition` (older, worse accuracy on Indian faces in varied lighting).
- Matching: cosine similarity in `pgvector`; 150 staff × 3-5 enrollment templates ≈ 750 × 512-d vectors — brute-force exact search, sub-millisecond. Threshold ~0.45-0.5 cosine similarity, tune during pilot; log all scores.
- Anti-spoofing (photo-on-phone attack): v1 use **MiniFASNet (Silent-Face-Anti-Spoofing, minivision-ai repo)** — a 1.9 MB ONNX model, ~10 ms CPU — plus policy deterrents (store the punch photo, random admin audits, punches visible to the person on screen). Skip active blink-liveness in v1; it slows every punch.

**CPU sizing:** one punch = detect (~80-150 ms) + embed (~60-120 ms) + spoof check (~10 ms) + match (<1 ms) ≈ **250-400 ms on 2 cores of a Ryzen 5/7 mobile-class CPU**. Peak load is shift change: ~60 people in 15 min = 1 punch/15 s — trivially served. Allocate 2 dedicated cores + 3 GB RAM to the container. **No GPU.** Enrollment: 3-5 photos per staff member via an admin web page (front, slight left/right, with/without glasses/mask-down), re-enroll on repeated false rejects.

**DPDP Act 2023 note:** biometric data — collect written consent at enrollment, store embeddings + punch photos encrypted at rest (LUKS full-disk covers this), define retention (e.g., punch photos 90 days, then keep only the event row), document purpose limitation. Feed this to the compliance section.

## 4. Local server

| Option | Cost (INR) | Trade-off |
|---|---|---|
| **Mini-PC (Beelink SER5 Max / Minisforum UM790 / ASUS NUC 14): Ryzen 7 / Core i5-13xx, 32 GB RAM, 1 TB NVMe** | ₹40-60k | No ECC, but silent, 15-45 W, tiny; buy TWO and the redundancy beats one tower's ECC |
| Tower server (Dell PowerEdge T150, Xeon E-2314, 16-32 GB ECC) | ₹90-130k | ECC + iDRAC, but noisy, 100 W+, overkill for this load |
| Repurposed desktop | ₹0-25k | Unknown health of PSU/disks — false economy for the system the hospital runs on |

**Recommendation: two identical mini-PCs — primary (₹~50k) + cold/warm standby (can be the cheaper ₹30k variant), 32 GB RAM, 1 TB NVMe + add a 2nd internal 1 TB SATA SSD for local backups.** Total ≈ ₹85-95k, still under one tower server. The standby holds nightly restored backups (this doubles as the continuous restore drill, §8).

**OS: Ubuntu Server 24.04 LTS, headless, with Docker.** Windows arguments (local IT familiarity) lose to: forced update reboots, licensing cost, worse Docker, and the reality that all admin will be done by the dev team over SSH/Tailscale anyway — the hospital staff never touch the server OS. Enable unattended-upgrades for security patches only, LUKS encrypt the data partition, install **Tailscale** for remote support access by the developers (works through NAT, no port forwarding, free tier).

**UPS:** load = mini-PC (~45 W) + switch (~15 W) + 2 APs (~20 W) + router ≈ 100 W. A 1 kVA line-interactive UPS (APC BVX1200 / Luminous ~₹6-8k) gives 45-90 min — enough to bridge to the hospital generator/inverter. Connect via USB and run **NUT (Network UPS Tools)** to trigger graceful shutdown at 20% battery. Put the kiosk tablet's AP and the reception PC on UPS/inverter circuits too, or attendance and registration die during cuts.

**Physical placement:** a lockable, ventilated 6U wall-mount network cabinet (₹5-7k) in the admin/records office — not the pharmacy store (humidity), not reception (theft/tampering). Server, switch, router, UPS all in the cabinet; label everything.

## 5. Network

- **Wired backbone for anything that matters:** reception PC(s), doctor-room PCs, pharmacy PC, token TV player, and the server on gigabit Ethernet (Cat6, one 16-port unmanaged/smart switch, TP-Link TL-SG1016D ₹6-7k). Wi-Fi (2× TP-Link Omada EAP225/EAP245, ₹5-9k each, one dedicated AP within 5 m of the kiosk tablet) is for the tablet, doctors' laptops/phones only. Separate SSID for staff vs any patient/guest Wi-Fi; guest VLAN or at minimum client isolation so patients can't reach the server.
- **Addressing:** DHCP reservations on the router; server fixed at e.g. `192.168.10.10`. **Do not rely on mDNS** (`.local` is flaky on Android and older Windows). Instead: buy a real domain (~₹800/yr, e.g. `hospitalname.in`), run split-horizon DNS — the on-prem server runs `dnsmasq` (or use router DNS override) resolving `app.hospitalname.in → 192.168.10.10`, and point all DHCP clients at it.
- **TLS (required for kiosk camera):** run **Caddy** as reverse proxy with a **Let's Encrypt wildcard cert via DNS-01 challenge** (needs internet only at renewal, every ~60 days — fine given intermittent connectivity; cert remains valid offline). This avoids installing a private CA root on every device. Fallback option: `mkcert` private CA pushed to the handful of hospital devices — acceptable but higher ongoing friction.
- **Failure modes & mitigations:** (a) Internet down → zero impact by design; backups and cert renewal queue up. (b) Wi-Fi flaky at kiosk → PWA service worker + IndexedDB: capture punch + photo + local timestamp, mark "pending", background-sync when reachable; server dedupes by (device, timestamp). Show clear on-screen state: "recorded, will sync". (c) Router/DNS dies → wired clients can still reach the server by bookmarked IP (keep an `https://192.168.10.10` alt route with the cert's IP SAN or an HTTP fallback page); keep one cold spare router with config backup. (d) Kiosk tablet dies → any staff phone can open the same PWA URL as emergency punch station (admin-unlockable mode), and manual attendance entry exists in the admin UI.

## 6. Printing

- **Prescriptions (A4/A5 laser):** generate **server-side PDF with WeasyPrint** (pixel-stable, doctors' letterhead as template, A5 default with A4 option) rather than raw browser CSS printing — consistent output regardless of client browser/PC. The browser opens the PDF and prints. For reception/doctor rooms where the print dialog is friction, run Chrome with `--kiosk-printing` (silently prints to the default printer). One mono laser per consultation room + reception: **Brother HL-L2321D (duplex, ₹12-14k) or HP Laser 1008w**, USB-attached to the room PC (simplest) — avoid shared network printing in v1.
- **Tokens (thermal):** print **server-side via ESC/POS** — `python-escpos` straight to a network/USB thermal printer at reception (**Epson TM-T82 ₹11-13k, or TVS-E RP 3230 ₹8-9k**, 3-inch). No browser dialog, sub-second, prints token no., patient name, doctor, timestamp, QR of visit ID. Registration submit → Django task fires the print. Keep 2 spare paper rolls taped inside the counter.
- Avoid QZ Tray (licensing/complexity) — the two paths above cover everything.

## 7. Auth, roles, audit

- **Roles:** Django Groups → `admin`, `doctor`, `nurse`, `receptionist`, `pharmacist`, with object-level rules where needed (a doctor edits only their own prescriptions; pharmacist read-only on Rx; receptionist no clinical fields). Every user is an individual account — **no shared logins**, enforce at training and by making per-user login fast.
- **Shared-computer sessions:** idle auto-lock at 5 min (10 for doctor rooms) to a lock screen; re-auth via **per-user 6-digit PIN** (POS-style user-tile picker) so switching users at reception takes 3 seconds; full password only at first daily login. `django-axes` for lockout after 5 failures. Prescription finalize/sign action always re-confirms the doctor's PIN.
- **Audit:** `django-auditlog` on Patient, Visit, Prescription, AttendanceEvent, User/role changes — append-only table (revoke UPDATE/DELETE at the Postgres role level), capturing actor, timestamp, IP/device, before/after diff. Attendance punches additionally keep the photo + confidence score for dispute resolution. Retain audit ≥ 3 years (aligns with typical Indian medico-legal record expectations; final numbers from the compliance section).
- **Legal validity of prescriptions (v1):** print + **physical wet signature** with doctor's name, qualifications, and state medical council registration number on the printout — this is the unambiguous legal path; defer DSC/eSign digital signing and ABDM/ABHA integration to v2 (but keep the ABHA ID column and FHIR-friendly field naming now).

## 8. Backups

Data volume estimate: DB ≤ 5 GB/yr; punch photos ~ 60 staff-days × 2 × 50 KB ≈ 2-3 GB/yr → total well under 50 GB for years.

- **Local, continuous:** **pgBackRest** — full backup nightly to the second internal SSD + WAL archiving every 5 min (point-in-time recovery). Files (photos, uploads) rsnapshot/borg to the same disk nightly.
- **Standby restore (the killer feature):** every night, the standby mini-PC pulls the latest backup and actually restores it into a running stack — this is an automated **daily restore drill** and a warm failover: if the primary dies, swap the DNS entry to the standby and you're live with ≤24 h-old data, or restore latest WAL from the primary's disk if it survived.
- **Cloud, encrypted:** **restic → Backblaze B2** ($6/TB/mo; this dataset ≈ **<$1/month**). Client-side AES-256 encryption (key stored in the admin's password manager AND printed in a sealed envelope in the hospital safe — losing the restic key = losing the backups). Runs hourly via systemd timer, silently skips when offline, retries on reconnect; alert (email/WhatsApp via Twilio or a simple cron + msg91) if last successful cloud snapshot > 48 h old. Alternatives: Cloudflare R2 ($0.015/GB, no egress fee) or AWS S3 ap-south-1 (data-residency optics if DPDP guidance tightens) — B2 wins on simplicity/cost; switch to S3 Mumbai only if a compliance requirement for India-resident data emerges.
- **Targets:** RPO — 5 min local (WAL) / 1-24 h cloud. RTO — 1 h to standby (practiced), 4-8 h bare-metal from cloud. Quarterly *manual* full-restore drill from cloud to a laptop, scripted and checklisted.

## 9. Deployment & updates

**Docker Compose on the on-prem box** (vs bare install: bare is marginally simpler day 1 but makes rollback, standby-parity, and the Python/ONNX dependency stack painful). Services: `caddy`, `web` (Django + gunicorn), `facesvc` (FastAPI + ONNX), `postgres:16`, `pgbackrest` sidecar/cron. Pin exact image tags (`:v1.4.2`), never `:latest`.

Update pipeline: GitHub private repo → GitHub Actions builds/tests → pushes images to **GHCR** → on-prem `update.sh` (run manually or on a "update available" flag when internet is up): (1) pgBackRest full snapshot, (2) `docker compose pull`, (3) run Django migrations — **enforce backward-compatible (expand/contract) migrations** so old code runs against new schema, (4) restart, (5) health-check endpoint `/healthz` (DB, facesvc, disk space, last-backup age); on failure auto-rollback: re-point compose to previous tag, restart, restore DB only if a migration was destructive (which policy forbids). Keep the previous two image versions cached locally so rollback works offline. **No Watchtower/auto-updates** — updates happen during OPD off-hours with a human able to check. Ship updates roughly fortnightly during rollout, monthly at steady state.

## 10. Phased build order (1-2 devs; weeks assume 2 devs — multiply ~1.7× for one)

| Phase | Weeks | Deliverable |
|---|---|---|
| 0. Foundation | 1-2 | Server + network + Docker + Caddy/TLS/DNS in place; Django skeleton, auth + roles + PIN relogin, Patient registry CRUD, CI, backup pipeline running from day one |
| 1. OPD core | 3-6 | Registration, appointments, token issue + thermal print, live queue board (HTMX) + token TV page, visit lifecycle, basic visit history. **Hospital starts daily use end of week 6** |
| 2. E-prescription | 7-10 | Drug master (seed with the hospital's own ~300-600 item formulary via xlsx import — no reliable free national drug DB; budget 2 days of pharmacist data entry), Rx composer with per-doctor favorites/templates, dose shorthand (1-0-1 × 5d), WeasyPrint A5 output, prescription history on patient timeline |
| 3. Attendance | 11-14 | Face service + enrollment UI, kiosk PWA + Fully Kiosk rollout, offline punch queue, shift roster model, late/absent dashboards, monthly attendance export (xlsx for payroll) |
| 4. Hardening & pilot exit | 15-16 | Audit-log review UI, standby failover rehearsal, cloud restore drill, load/lighting tuning of face thresholds, staff training materials, on-call/runbook doc |

Rationale for order: OPD+tokens delivers visible daily value fastest and forces the patient registry (which prescriptions depend on); attendance is last because it has the most hardware/ML tuning risk and zero dependency from the other modules. Total: **~16 weeks / 2 devs (~8 person-months)**; capex ≈ ₹1.6-2.2 L (2 mini-PCs ₹85k, tablet+mount ₹16k, network+cabinet+UPS ₹30k, 3-4 laser printers ₹40k, thermal printer ₹10k, token TV + player ₹25k); recurring ≈ ₹2-3k/yr (domain + B2 + Fully Kiosk already one-time).