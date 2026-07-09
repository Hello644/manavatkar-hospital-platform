# Hospital Platform — Master Plan (Version 1)

**Status:** Planning approved-pending-review · **Date:** 2026-07-02 · **Build:** not started (by agreement)

Detailed planning documents this plan synthesizes:
- [docs/planning/clinical-opd-rx.md](docs/planning/clinical-opd-rx.md) — clinical/OPD & prescription functional spec
- [docs/planning/attendance-facial.md](docs/planning/attendance-facial.md) — facial attendance functional + technical spec
- [docs/planning/architecture-infra.md](docs/planning/architecture-infra.md) — architecture, hardware, network, backups, deployment
- [docs/planning/compliance-risk.md](docs/planning/compliance-risk.md) — DPDP Act, prescription law, retention, risk register
- [docs/planning/gap-analysis.md](docs/planning/gap-analysis.md) — completeness critique this plan incorporates
- [docs/planning/letterhead-spec.md](docs/planning/letterhead-spec.md) — transcription of the real letterhead + print-template requirements

---

## 1. What we are building (and not)

An integrated **hospital management platform** — one web application, served from a small server inside the hospital, opened in a browser on every desk — not a literal operating system. It must keep working with the internet down; internet is used only for backups, WhatsApp sharing, and remote support.

**Facility profile:** **Dr. Manavatkar Hospital ("Kshitij" intensive-care dept.), Jamner Road, Bhusawal, Maharashtra.** Two consultant doctors — Dr. Rajesh Manavatkar (M.D. Medicine, Reg. No. 80166, general medicine) and Dr. Madhu Rajesh Manavatkar (M.B.B.S., D.G.O., Reg. No. 82243, gynecology). ~10–50 beds, nursing staff on rotating shifts, 24-hr emergency services, OPD closed Tuesday evenings. Regional language: **Marathi**. Build team: **the owner (Dr. Rajesh) + Claude, working together in this repository.**

## 2. Version-1 scope

| In v1 | Explicitly out of v1 (backlog for v2) |
|---|---|
| Patient registry (shared by all modules) | Pharmacy inventory & billing |
| OPD workflow: registration, appointments, token queue + waiting-room display, vitals, visit history | IPD/ward management (v1 records "advised admission" as a disposition only) |
| E-prescriptions: fast composer, printed on letterhead, PDF archive, WhatsApp record-copy | Lab module (v1: scan/photo of report can be attached to a visit) |
| Facial attendance: tablet kiosk, shifts/roster, absentee & late dashboards, payroll export, basic leave | Patient-facing portal / online booking |
| Consult-fee capture, receipt numbering, daily collection register (billing-lite) | Full accounting, insurance/TPA |
| Audit logging, backups, standby server, degraded-mode SOPs | ABDM/ABHA integration (designed-for, not built), eSign/DSC digital signatures, drug-interaction engine, SMS/WhatsApp automation at scale |

Scope discipline: change requests during the build go to a written v2 backlog, not into v1.

## 3. Users & roles

`admin` (owner/manager), `doctor` (incl. time-boxed **locum** accounts with their own SMC registration number — hard-validated before first Rx), `nurse`, `receptionist`, `pharmacist` (read-only on Rx), and `staff` (self-service: leave requests, own attendance view; login = employee code + PIN, PIN reset by admin). Individual accounts only — no shared logins. Shared desks use fast user-switching: 6-digit personal PIN over a POS-style user picker; idle lock at 5 min. Prescription creation is restricted to `doctor` accounts carrying a registration number.

**Everything is admin-editable, nothing hardcoded (owner requirement):** hospital details, doctor blocks (name, qualifications, registration number, specialty, fees, letterhead text), staff list, shifts, formulary, OPD timings — all maintained from admin screens in the UI. No developer needed to change anything that prints on a prescription or drives attendance.

## 4. Module A — Patient registry & OPD

Full spec: [clinical-opd-rx.md](docs/planning/clinical-opd-rx.md). Key points and plan-level decisions:

- **UHID:** `XXX-26-004217-3` — 3-letter hospital code + 2-digit year + 6-digit sequence + Luhn check digit; printed as Code-128 barcode on OPD slip and Rx (single symbology everywhere).
- **Registration** completes in <60 s: name, mobile (or "no phone" flag), age/DOB, sex; everything else optional. Includes DPDP privacy-notice checkbox; **minors additionally require guardian name + relationship**. `old_file_number` field cross-references existing paper files. Duplicate detection = exact mobile + name-trigram similarity, tuned down for shared-phone households (mobile match alone never auto-flags); staff decides, admin-only merge tool.
- **OPD flow:** walk-in and appointment paths converge on per-doctor daily token queues (`A-042`); checked-in appointments interleave ahead of walk-ins; emergency flag jumps queue (audit-logged). Nurse vitals station (weight mandatory under age 12) → doctor's single keyboard-first consult screen (history rail, allergy banner, Rx composer) → **Print & Next** ends the visit and auto-calls the next token.
- **Visit disposition (required):** home / follow-up / advised admission / referred out / expired — this is a hospital with beds; OPD→IPD handoff must exist in the record even with IPD out of scope.
- **MLC (medico-legal) workflow:** MLC flag at registration or during visit; quick-registration for unknown/unconscious patients ("UNKNOWN male ~40"); brought-by/police-station/injury fields; "MLC" watermark on all prints; WhatsApp sharing blocked for MLC documents; 10-year retention hook.
- **Waiting-room display:** any Android TV/HDMI stick opening `/display/opd`. **Privacy rule: token numbers only — never patient names or diagnoses on the public display or in announcements.** Audio announcements use **pre-generated MP3 snippets** rendered server-side in Hindi + regional language (token numbers are a small finite set) — not browser TTS, which silently fails offline on cheap Android devices.
- **Doctor-absence handling:** one action bulk-cancels/reschedules a doctor's day, produces a front-desk call list, and can redirect the live queue to another doctor.
- **Follow-ups:** date chips print on the Rx and feed a front-desk "due today/this week" call list; WhatsApp/SMS reminders are a queued outbox that degrades silently offline.
- **Fees (billing-lite):** consult fee + payment mode per visit, sequential receipt series, refund flag with reason, daily collection register (cash/UPI split), doctor-wise OPD count and revenue report — the first report the owner will ask for.

## 5. Module B — E-prescriptions

Full spec: [clinical-opd-rx.md](docs/planning/clinical-opd-rx.md) §3–8. Key points:

- **Composer:** one drug per row, fully keyboard-driven; autocomplete over the hospital's own formulary ranked by the doctor's own usage; dosage shorthand (`1-0-1 x 5`, OD/BD/TDS/HS/SOS/STAT) parsed to structured data; quantity auto-computed; per-doctor favorites and diagnosis-based Rx templates (target: template Rx < 30 s, any Rx 45–90 s); free-text fallback row so the doctor is never blocked.
- **Formulary (decision, revised — no purchase register exists):** the hospital's **own curated formulary**, seeded three ways: (1) generics from NLEM 2022 + Jan Aushadhi public lists; (2) a **starter list of ~250 common Indian OPD brands for general medicine + gynecology, drafted by Claude and reviewed/pruned by the doctors** (reviewing a spreadsheet is far faster than writing one from memory); (3) organic growth — the composer's free-text fallback feeds an admin "add to formulary" queue, so the list converges on real prescribing habits within the first weeks. Sample prescriptions, if found later, accelerate (2). No scraped datasets, no commercial API (offline-first conflict). Each drug stores: generic (INN), brand, strength, form, schedule class (H/H1/X/OTC), ingredients, default signature, pediatric mg/kg where applicable.
- **Legal format:** generic name in caps with brand beneath; doctor name, qualifications, SMC council + registration number; hospital details; patient name/age/sex/UHID (address auto-required for scheduled drugs); Schedule H1 warning box; Schedule X prints in duplicate, duration-capped, never shared digitally; NDPS excluded from formulary by policy.
- **Signature (decision, resolves draft conflict):** the **printed sheet with wet-ink signature + stamp is the legal prescription**. No scanned-signature images anywhere — a scanned image is not a valid signature under the IT Act and is a forgery risk. Aadhaar eSign / DSC tokens deferred to v2.
- **Outputs:** **A4 default, matching the real letterhead** (see [letterhead-spec.md](docs/planning/letterhead-spec.md)); pre-printed letterhead mode (body-only overlay at calibrated offsets, filling the letterhead's existing blanks for name/age/date/sex/weight/pulse/SpO₂/BP/follow-up) or full-render mode from the design file. Every Rx prints a "Prescribed by: Dr. ___ (Reg. no. ___)" line — the shared two-doctor letterhead makes prescriber attribution mandatory. **One rendering pipeline (decision):** a single HTML template → **WeasyPrint** server-side PDF, used for both the immutable archive (SHA-256-hashed, stored per visit) and printing; consult-room PCs print silently via Chrome `--kiosk-printing`. Reprints watermark "DUPLICATE"; post-print edits create a new version marked "REVISED".
- **WhatsApp sharing:** day one = manual `wa.me` share of the archived PDF from the front desk, watermarked "record copy — signed original issued to patient", **with per-share confirmation of the destination number** (shared family phones are a confidentiality leak); blocked for Schedule X and MLC. Automated WhatsApp Business API outbox is v1.1.
- **Safety checks in v1:** ingredient-level allergy hard-stop (typed override reason, logged), duplicate-ingredient warning (PCM in two brands), curated max-dose warnings (~30 drugs), pediatric weight-required block, inline mg/kg calculator from today's weight. Full interaction engine deliberately deferred — and the Rx must never imply interaction checking was done.
- **Edge cases covered:** repeat/refill queue (doctor one-click approves; fresh dated Rx, never re-issued PDFs), in-OPD administrations create nurse tasks (batch no., route, time) and print under a separate "administered in hospital" section, composer autosaves every 5 s.

## 6. Module C — Facial attendance

Full spec: [attendance-facial.md](docs/planning/attendance-facial.md). Key points and decisions:

- **Kiosk (decision):** Android tablet (Samsung Tab A9+/Lenovo M10 class, ₹13–18k + spare) wall-mounted at the staff entrance, camera center **1.40 m**, LED panel above, never facing a window; Ethernet via USB-C hub preferred. Runs a **PWA locked in Fully Kiosk Browser** — no native app. Offline store-and-forward via IndexedDB/service worker: if the server is unreachable, the punch (frame + timestamp) queues locally, shows "recorded — will sync", replays later; punches are never lost. The tablet's battery rides out power cuts.
- **Recognition (decision, adopts the attendance spec):** all inference on the LAN server, CPU-only — SCRFD-500MF detection + ArcFace (`buffalo_l`) 512-d embeddings via ONNX Runtime + MiniFASNet passive liveness; <150 ms per frame, vote over 2–4 frames. Matching = brute-force cosine in-process (~1,800 vectors; no vector DB). Embeddings stored in Postgres alongside staff records.
- **Thresholds:** auto-accept at cosine ≥ 0.42 **and** top1−top2 margin ≥ 0.08 (sibling/lookalike guard); 0.32–0.42 → on-screen "Are you X?" confirm; below → retry or PIN. Tuned on-site in week 1 from logged score distributions.
- **Anti-spoofing honesty:** passive liveness + multi-frame micro-motion + every punch stores a photo thumbnail — this deters photo/buddy-punching and makes it *auditable*, but it is not marketed as spoof-proof. The real deterrent at this scale is the stored photo + visible mounting + policy.
- **Enrollment:** admin-supervised only, 5–8 samples with quality gates, <90 s/person (~one afternoon for all staff); adaptive gallery update absorbs appearance drift; auto-flag for re-enrollment on falling scores or repeated PIN fallbacks.
- **IN/OUT (decision):** shift-aware inference with a 3-second on-screen "wrong? tap to switch" override. **Raw punches are stored as direction-less timestamped events; IN/OUT is a derived, re-runnable interpretation** — corrections never touch raw events.
- **Shifts & the midnight problem:** roster entries spawn `shift_instance`s with absolute timestamps; punches attach to the instance whose window they fall in, never to a calendar date — a 07:05 OUT correctly credits yesterday's night shift. Split shifts = two instances per day. Missed punches auto-close flagged into an admin regularization queue (mandatory reason, audit-logged).
- **Edge cases (from gap analysis):** shift-swap request/approval flow (ubiquitous among nurses — without it every swap is a manual correction); **punch-exempt category** for visiting consultants/part-timers so they don't pollute absentee dashboards; on-duty (OD) status for staff called in off-roster.
- **Dashboards:** live "who is in right now" board (also the fire-muster list), today's absentees/latecomers/exceptions with punch photos, monthly register (staff × days), payroll `.xlsx` export (format signed off by whoever runs payroll *before* build), basic leave types/balances/one-step approval.
- **Consent & privacy (DPDP):** explicit bilingual consent at enrollment (digital record + signed paper form); **PIN-only attendance for decliners with no adverse consequence** — that's what makes consent genuine and is also the withdrawal path; embeddings + one reference photo stored (no raw videos); **punch photos hard-deleted after 45 days** (single number, appears in the consent notice); biometric purge within 30 days of exit (attendance *records* kept 3 years); admin consent-registry screen.

## 7. Architecture & stack

Full detail: [architecture-infra.md](docs/planning/architecture-infra.md).

- **Django 5.x monolith** (auth, roles, admin CRUD for masters, migrations, auditlog) + **HTMX/Alpine** server-rendered UI — right call for a LAN app on cheap PCs; no SPA build pipeline. **FastAPI face-recognition microservice** in its own container (isolates the ~2 GB model footprint; can crash without taking down OPD). **PostgreSQL 16** (+ `pg_trgm`; pgvector as embedding storage only).
- **Queue updates (decision):** SSE/HTMX polling every 3–5 s in v1 — good enough for a token board; WebSockets/Redis only if it ever isn't. Auto-call-next stays.
- **Language (decision):** English UI for v1 **with Django i18n scaffolding from day 1** (retrofit is expensive); patient-facing artifacts (Rx instruction snippets, queue announcements, consent notices) are tri-lingual — **English / Hindi / Marathi** (confirmed: Bhusawal, Maharashtra; the letterhead is Marathi-first). Devanagari fonts embedded in the PDF pipeline. Patient names stored as typed in Latin script — keeps trigram search working.
- **Audit:** `django-auditlog` for mutations **plus custom middleware logging every view of a patient's clinical chart** (explicitly scoped — the library doesn't do read-audit). Append-only at the Postgres-grant level. Every punch stores confidence + photo. Security logs ≥ 1 year, clinical audit ≥ 3 years.
- **Time authority:** the server is the sole timestamp authority (chrony + local RTC for multi-day offline drift); kiosk store-and-forward punches carry device time and are reconciled at sync; clock-drift alarm on the health endpoint.
- **TLS on LAN** (required for the kiosk camera): real domain (~₹800/yr) + Caddy with Let's Encrypt DNS-01 wildcard — renewal needs internet briefly every ~60 days, cert works offline. Split-horizon DNS on the router/dnsmasq; bookmarked-IP fallback if DNS dies.
- **Deployment:** Docker Compose on the server (caddy / web / facesvc / postgres / backup sidecar), pinned image tags, GitHub Actions → GHCR, manual off-hours `update.sh` with pre-update snapshot, health-check, offline-capable rollback (previous two images cached). Expand/contract migrations only. No auto-updates.

## 8. Hardware & network (shopping list)

| Item | Spec | Est. cost (₹) |
|---|---|---|
| Primary server | Mini-PC (Ryzen 7/i5 class), 32 GB RAM, 1 TB NVMe + 1 TB SATA (backup disk), Ubuntu Server 24.04 + Docker, LUKS | 50k |
| Standby server | Cheaper identical-class mini-PC; nightly auto-restore (doubles as daily restore drill) | 30–35k |
| Kiosk tablet ×2 (1 spare) | Samsung Tab A9+/Lenovo M10 class + locking wall mount + USB-C Ethernet/PD hub + Fully Kiosk licence | 30–35k |
| Network | 16-port gigabit switch, 2× ceiling APs (one near kiosk), Cat6 runs, guest-isolated patient Wi-Fi, 6U lockable cabinet | 25–30k |
| UPS | 1 kVA line-interactive + NUT graceful shutdown; **printers and doctor-room PCs on inverter circuits** (else no Rx printing mid-power-cut) | 7–8k |
| Printers | Mono duplex laser per consult room + reception (Brother HL-L2321D class); 1 thermal token printer (Epson TM-T82/TVS RP 3230, ESC/POS server-driven) | 50k |
| Token TV | Any Android TV/stick opening the display URL | 15–25k |
| **Capex total** | | **≈ 2.0–2.3 L** |
| Recurring | Domain + Backblaze B2 backups (<$1/mo) + misc | ~3k/yr |

## 9. Compliance & privacy (India)

Full detail: [compliance-risk.md](docs/planning/compliance-risk.md). The build-to standard is **DPDP Act 2023 + Rules 2025** (substantive obligations bite May 2027 — the system will be live past that; penalties are existential). Practical consequences already baked into the modules above: consent flows (staff biometrics, patient registration notice, guardian for minors), data minimization, purge-on-exit, breach-response SOP + pre-drafted notification template, named contact person.

- **Record retention (drives schema):** clinical data is **immutable, soft-delete only, never auto-purged** (litigation exposure realistically 5–10 years; MLC 10+; pediatric until age 21). Corrections create versions. `is_mlc` flag on visits.
- **Prescription law:** only RMP-role users with registration numbers can prescribe; mandatory Rx elements enforced by the template; schedule-drug behaviors (H1 box, X duplicate/caps) enforced by formulary flags; **wet-ink signature is the legal instrument in v1**.
- **ABDM/ABHA (decision):** not integrated in v1 (needs internet at point of care + certification cycle), but designed-for now: nullable `abha_number`/`abha_address` on patients, HPR/HFR ID fields, UUID keys, ISO timestamps, **prescriptions stored as structured line items** (FHIR-mappable later). Register the facility on HFR via the portal now — free, no software needed.

## 10. Resilience & operations

- **Backups (3-2-1):** pgBackRest nightly full + 5-min WAL to the second internal SSD; restic → Backblaze B2 hourly (client-side encrypted; key in password manager AND sealed envelope in the hospital safe); alert if last cloud snapshot > 48 h. **Biometric templates and punch photos are excluded from cloud backup** (decision — lowest-risk DPDP posture); they live in local encrypted backups only, and a total-loss disaster means one afternoon of re-enrollment. RPO 5 min local / ≤24 h cloud; RTO 1 h to standby.
- **Standby & failover:** nightly restore onto the standby is the drill. Promotion is **one-way**: a laminated, admin-executable runbook (no IT staff on site) promotes the standby; the failed machine is always wiped and returns as the new standby — the two are never both live, which eliminates the merge/reconciliation problem. Quarterly scripted cloud-restore drill.
- **Degraded mode (server down during OPD):** a printed paper kit lives at reception — pre-printed token pads, Rx pads, manual attendance sheet — plus a **back-entry workflow**: the system provides "back-dated entry" screens so the paper hours are keyed in after recovery (flagged as back-entered, audit-logged).
- **Post-launch support model (to agree before build):** who receives health/backup alerts, on-call terms after handover, spare-hardware custody, and who owns formulary additions and roster admin day-to-day.

## 11. Rollout & training (per gap analysis — this was missing from the drafts)

1. **Sandbox instance** with dummy patients for training; named super-user per shift; typing-proficiency check for desk staff.
2. **Phased cutover with exit criteria:** OPD/tokens first (exit: one full week with zero paper tokens) → prescriptions (paper Rx remains a sanctioned fallback for month 1; exit: owner-doctor consistently under 90 s/Rx) → attendance (**2-week parallel run against the existing register; payroll sign-off gate before the physical register is retired**).
3. **Data migration policy:** no bulk import of paper records. Patients are re-registered on next visit (old file number cross-referenced). Leave **opening balances** entered at go-live; attendance goes live at a payroll-month boundary.
4. Owner announces the biometric-attendance purpose and the PIN alternative at a staff meeting before enrollment day.

## 12. Build roadmap & budget

Assumes 2 developers (multiply durations ~1.7× for one). Includes the gap-analysis additions.

| Phase | Weeks | Deliverable |
|---|---|---|
| 0 — Foundation | 1–2 | Server, network, TLS/DNS, Docker, Django skeleton, auth/roles/PIN switching, patient registry, CI, **backups running from day one** |
| 1 — OPD core | 3–6 | Registration + consent capture, appointments, tokens + thermal print, queue board + TV display + MP3 announcements, vitals, visit lifecycle + disposition, MLC path, fees/receipts/collection register. **Hospital starts daily use end of week 6** |
| 2 — E-prescriptions | 7–10 | Formulary import + curation tooling, Rx composer (favorites/templates/shorthand), safety checks, WeasyPrint A5 pipeline + silent printing, archive + reprint/revision rules, WhatsApp manual share, chart-view read-audit middleware |
| 3 — Attendance | 11–14 | Face service, enrollment + consent registry, kiosk PWA + offline queue, roster/shift instances + swaps, dashboards + exceptions, payroll export, leave basics |
| 4 — Hardening & pilot exit | 15–17 | Threshold tuning on-site, failover rehearsal + laminated runbook + paper kit, cloud restore drill, audit review UI, training materials, parallel runs & sign-off gates (§11) |

**Totals:** ~17 weeks / 2 devs (≈ 8.5 person-months) · capex ≈ ₹2.0–2.3 L · recurring ≈ ₹3k/yr + developer support contract.

## 13. Top risks (full register in [compliance-risk.md](docs/planning/compliance-risk.md) §6)

1. **Face-recognition disputes** → photos + confidence stored per punch, PIN fallback, admin corrections with reasons, threshold favors false-reject, 2-week parallel run.
2. **Doctor adoption** ("paper takes 30 s") → speed is the #1 design goal of the composer; pilot with the owner-doctor; measure time-per-Rx before rollout.
3. **Single-server failure** → standby + one-way promotion runbook + paper kit.
4. **Data loss/ransomware** → 3-2-1 backups, offline copy, monthly restore proof, soft-delete-only schema.
5. **Solo/small dev team (bus factor)** → boring stack, runbook as a deliverable, sealed-envelope credentials.
6. **Scope creep** → signed one-page v1 scope; everything else is written v2 backlog.
7. **Staff privacy pushback** → genuine PIN alternative, consent-first enrollment, deletion policy in writing.
8. **Power/network outages** → UPS + inverter circuits incl. printers, kiosk offline queue, LAN-only critical path ("unplug the router" test is an acceptance criterion).

## 14. Decisions log (conflicts between drafts, resolved)

| # | Conflict | Decision |
|---|---|---|
| 1 | Scanned signature images on PDFs / WhatsApp legality | No signature images ever; wet-ink print is the legal Rx; WhatsApp = watermarked record copy, number confirmed per share, blocked for Schedule X & MLC |
| 2 | Biometrics in cloud backup | Excluded from cloud; local encrypted backup only; re-enroll after total disaster |
| 3 | PDF engine (Puppeteer+SumatraPDF vs WeasyPrint+kiosk-printing) | WeasyPrint single pipeline; Chrome `--kiosk-printing` for silent room printing |
| 4 | Registration vs consent duties | Privacy checkbox + guardian fields for minors added; <60 s target holds for adults |
| 5 | Face-rec parameters diverged | Attendance spec adopted wholesale (SCRFD-500MF, buffalo_l, 0.42 + 0.08 margin, 5–8 samples, numpy matching; pgvector = storage only) |
| 6 | Read-access audit unscoped | Custom middleware explicitly scoped in Phase 2 |
| 7 | WebSocket <2 s vs HTMX polling | SSE/polling 3–5 s in v1 |
| 8 | UHID formats & symbology | `XXX-YY-######-L` + Code-128 everywhere |
| 9 | Punch-photo retention 30/90 days | **45 days**, stated in the consent notice |
| 10 | Kiosk native vs PWA, SQLite vs IndexedDB | PWA in Fully Kiosk + IndexedDB store-and-forward |
| 11 | Liveness: commercial SDK vs passive | Passive MiniFASNet + multi-frame + policy deterrents; no blink challenge, no commercial SDK |
| 12 | Attendance rows store direction? | Raw direction-less events; IN/OUT derived and re-runnable |
| 13 | Formulary seeding | NLEM 2022 + Jan Aushadhi seed → pharmacist maps brands via xlsx |
| 14 | Camera height / server RAM | 1.40 m camera center; 32 GB RAM |

**Round 2 — owner inputs (2026-07-02):**

| # | Input | Decision |
|---|---|---|
| 15 | Real letterhead received (A4, Marathi, two-doctor, vitals blanks) | Rx default = A4; template fills the letterhead's existing blanks; prescriber-attribution line mandatory; spec in [letterhead-spec.md](docs/planning/letterhead-spec.md) |
| 16 | "Registration details & staff list editable from admin profile" | All masters (hospital, doctors, staff, shifts, formulary, timings) are admin-editable UI screens — nothing hardcoded |
| 17 | Location: Bhusawal, Maharashtra | Regional language = Marathi; Maharashtra Nursing Home Registration Act applies; UHID code suggestion `DMH` |
| 18 | Build team | Owner + Claude build it together in this repo — runbooks written for the owner as operator |
| 19 | Letterheads are already color offset-printed | Print mode = **body-only text overlay** at calibrated positions filling the existing blanks; no design file needed — just ~20 blank sheets for calibration in Phase 2 |
| 20 | No pharmacy drug list / purchase register exists | Formulary seeded from NLEM + Jan Aushadhi + a Claude-drafted ~250-drug starter list reviewed by the doctors, then grown via the free-text→add-queue flow |
| 21 | Staff list | Owner will type staff + shift timings directly into the admin screens once built; shift defaults designed together in Phase 3 |

## 15. Inputs checklist

| # | Input | Status |
|---|---|---|
| 1 | Letterhead | ✅ Image transcribed ([letterhead-spec.md](docs/planning/letterhead-spec.md)); sheets are color offset-printed → body-only overlay mode. Need ~20 blank sheets for print calibration (Phase 2, not now) |
| 2 | Doctor details | ✅ From letterhead (Dr. Rajesh — MD Medicine, Reg. 80166; Dr. Madhu — MBBS DGO, Reg. 82243). **Confirm reg. numbers + which State Medical Council** (presumably Maharashtra Medical Council); consult fees pending. Editable later from admin profile |
| 3 | State / language | ✅ Bhusawal, Maharashtra → Marathi |
| 4 | Staff list + shift patterns | ✅ Resolved: owner types these into the admin screens directly; late-grace policy + payroll format still to define together before Phase 3 |
| 5 | 10–20 real prescriptions per doctor (anonymized) | ◐ Optional accelerator — provide if convenient, not blocking |
| 6 | Pharmacy drug list | ✅ Resolved: none exists — formulary seeded from public lists + Claude-drafted starter list reviewed by doctors + grows from real usage |
| 7 | Hardware inventory (PCs, printer models, router, UPS/generator, internet reliability) | ⬜ Pending |
| 8 | Operational parameters (OPD timings — "closed Tue evening" noted; daily OPD volume; token scheme) | ◐ Partial |
| 9 | Policy sign-offs (biometric consent, privacy notice, retention, breach contacts, admin access) | ⬜ Drafts to be produced during build |
| 10 | Accounts (cloud backup, domain name, front-desk WhatsApp number, ABDM HFR registration) | ⬜ Pending |

## 16. Open questions

- Is there an existing attendance register/payroll format we must match exactly?
- Single staff entrance, or do we need to plan a second kiosk sooner than v2?
- Approximate daily OPD patient volume?
