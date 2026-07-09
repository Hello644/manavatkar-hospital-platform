# Facial Attendance Module — Functional + Technical Specification (v1)

## 1. Enrollment Flow

- **Who enrolls:** Admin-supervised only (HR/admin logs into an "Enroll Staff" screen on the kiosk tablet itself or any LAN PC with a webcam). Self-enrollment is disallowed to prevent ghost employees.
- **Prerequisite record:** Staff must already exist in the staff master (staff_id, full name, role, department, shift group, phone, joining date, photo consent flag — see §8).
- **Capture protocol:** **5 samples minimum, 8 recommended**: frontal neutral, frontal smiling, ~15° left, ~15° right, slight chin up/down; if the person routinely wears glasses, capture 2 samples with and without. If staff wear surgical masks routinely, capture 2 additional masked samples (stored as a separate "masked" template set).
- **Quality gates per sample (auto-enforced):** detection confidence ≥ 0.7; inter-eye distance ≥ 80 px; blur check via Laplacian variance ≥ 100; no more than one face in frame; pose yaw/pitch within ±25°. Reject and re-prompt otherwise.
- **What is stored:** the 512-d embedding per sample + ONE reference JPEG (for the admin UI and audit), not all raw captures. Gallery template = per-person set of embeddings (match against all, take max score) — better than averaging for pose variety.
- **Re-enrollment triggers:** (a) admin-initiated (beard/weight/glasses change, injury); (b) automatic flag when a staff member's 7-day rolling mean match score drops below threshold + 0.05, or ≥3 PIN-fallback punches in a month; (c) **adaptive gallery update**: after any high-confidence punch (score ≥ threshold + 0.15, liveness pass), optionally append that embedding to the gallery (cap gallery at 12 embeddings, FIFO-evict lowest-quality). This absorbs slow appearance drift without manual re-enrollment.
- **Enrollment time budget:** < 90 seconds per person; 120 staff ≈ one afternoon.

## 2. Recognition Pipeline

**Stages:** frame capture → face detection → alignment (5-point landmarks) → embedding → 1:N match against gallery → liveness → decision.

**Named open-source options:**

| Component | Option A (recommended) | Option B | Option C |
|---|---|---|---|
| Detection | **SCRFD-500MF** (InsightFace) — ~10-25 ms CPU at 640px | RetinaFace-MobileNet0.25 — similar speed, older | Google ML Kit Face Detection (on-tablet, free, detection only) |
| Embedding | **ArcFace R50/R100, InsightFace `buffalo_l` pack** (512-d, glint360k-trained) | `buffalo_s` (MobileFaceNet-class, ~3x faster, ~1-2% worse on hard cases) | dlib ResNet (99.38% LFW — measurably weaker, avoid) |
| Runtime | **ONNX Runtime CPU** | NCNN / TFLite (for on-tablet) | OpenVINO (Intel CPU boost, extra complexity) |
| Packaged alternative | **CompreFace** (Exadel) — self-hosted REST service wrapping InsightFace models, has enrollment UI & API out of the box | DeepFace (Python lib, wraps ArcFace/FaceNet; slower, research-grade plumbing) | — |

**Where inference runs — recommendation: on the LAN server, not the tablet.**
- Tablet = dumb kiosk: Android app (or Chrome-in-kiosk-mode PWA using `getUserMedia`) that detects "a face is present" cheaply (ML Kit or just motion), then POSTs a 640×480 JPEG frame (~40 KB) to `POST /api/v1/punch/recognize` over LAN. Round trip < 100 ms on wired LAN.
- Why server: one place to update models/thresholds, tablet stays cheap and replaceable, gallery never leaves the server (DPDP benefit), no per-device model conversion (NCNN/TFLite) engineering.
- On-tablet inference is Option B only if you later add multiple kiosks and want them to survive server outages fully; v1 handles server outage with store-and-forward instead (§9).

**Matching at 150 staff:** brute-force cosine similarity against ≤150×12 = 1,800 vectors of 512-d = <1 ms in numpy. No vector DB needed (do NOT add FAISS/Milvus at this scale).

**CPU-only feasibility (no GPU):** Yes, comfortably. On an i5-8th-gen-class server CPU: SCRFD-500MF ~15 ms + ArcFace R50 ~40-70 ms + MiniFASNet liveness ~20 ms ≈ **<150 ms per frame end-to-end**; process 2-4 frames per punch and vote. Server also runs the HMS web app fine concurrently — attendance load peaks at shift change (~40 punches in 15 min = trivial).

**Expected accuracy:** ArcFace-class models score 99.8%+ LFW / ~97-98% on harder benchmarks (IJB-C). For a closed set of 150 cooperative users with controlled lighting, realistic field expectation: **>99% true-accept on first glance, <0.1% false-accept** with the thresholds in §4. Failure residue (~1-3% of punches needing a second glance or PIN) is normal; design the UX for it rather than promising 100%.

## 3. Anti-Spoofing / Liveness (v1-realistic)

- **Primary: passive RGB liveness — MiniVision "Silent-Face-Anti-Spoofing" (MiniFASNet V2)**, MIT-licensed, ONNX-exportable, ~20 ms CPU. Catches most printed photos and phone-screen replays (screen glare, moiré, color-texture cues). Run on the same server frame; require liveness score ≥ 0.85 on at least 2 of 3 frames.
- **Cheap complementary checks:** (a) multi-frame requirement — 3 frames over ~600 ms with small landmark motion (a static photo held perfectly still fails micro-motion variance); (b) face-size sanity (a phone screen held close produces implausible inter-eye-distance/context ratios); (c) reject if a second face/phone-bezel-like rectangle is detected.
- **Policy defenses (the real deterrent at this scale):** kiosk mounted at a staffed/visible entrance (reception sightline or CCTV overlap); **every punch stores the captured frame** (thumbnail, 30-day retention) so buddy-punching is auditable and provable; disciplinary policy communicated at enrollment.
- **Honest limits (state these to the owner):** RGB-only liveness on a commodity tablet will NOT reliably stop high-quality video replay on a bright phone, 3D masks, or a determined insider. Robust liveness needs IR/depth cameras (purpose-built terminals, see §9 Option B). For a 30-120-person hospital where everyone knows everyone and punch photos are kept, RGB liveness + audit photos is proportionate for v1. Do not market it as "spoof-proof."

## 4. Thresholds, Lookalikes, Masks, Lighting, Fallback

- **Metric:** cosine similarity on L2-normalized embeddings. **Starting threshold 0.42** for `buffalo_l` (tune on-site in week 1 by reviewing score distributions; genuine punches typically land 0.55-0.75, impostors <0.30).
- **Lookalike/sibling guard (1:N specific):** auto-accept only if `top1 ≥ 0.42` AND `top1 − top2 ≥ 0.08`. If margin fails (two similar candidates — siblings do occur in small-town hospital staff), show a confirm screen: "Are you **Priya Sharma**? [Yes] [No — enter PIN]" and flag the punch `margin_review`. Never silently pick top-1 in the ambiguous band.
- **Three-band decision:** ≥0.42+margin → auto-accept; 0.32-0.42 → confirm-screen (tap yes + liveness must pass, punch flagged `low_confidence`); <0.32 → "not recognized, try again or use PIN."
- **Masks:** ArcFace accuracy drops 5-15% with surgical masks. v1 policy (recommended): on-screen prompt "please lower mask briefly" — one second, standard practice at Indian hospital biometric gates. Optional enhancement: match against the separate masked-template set at a higher threshold (0.48). Do not attempt periocular-only models in v1.
- **Lighting changes:** primary mitigation is physical (§9). Software side: enable camera auto-exposure lock on the face region; histogram-check frames and show "step closer / too dark" hints; re-tune threshold seasonally if needed.
- **Fallback check-in:** 6-digit personal PIN keypad on kiosk (PIN set at enrollment, hashed). PIN punch always: captures the frame anyway, marks the record `method=PIN`, and appears on the admin's daily exception list. Rate-limit: 5 wrong PINs → 60 s lockout. >3 PIN punches per person per month → auto-suggest re-enrollment. PIN mode is also the mandated path for any staff who decline biometric consent (§8).

## 5. Kiosk UX — Glance-and-Go

- **Idle screen:** clock + hospital logo; camera preview appears when a person is detected (attract mode).
- **Happy path (target < 2 s):** walk up → face box turns green → full-screen greeting **"Good morning, Sister Anita — IN 07:58"** with photo, green check, chime + short TTS (helps low-literacy staff and gives non-visual confirmation). Auto-resets in 2.5 s for the next person (shift-change queue throughput ~20/min).
- **IN vs OUT determination — options:**
  - (a) Toggle/parity (odd punch = IN, even = OUT): breaks badly on one missed punch, cascades errors. Reject.
  - (b) Explicit IN/OUT buttons before scan: unambiguous but adds a tap, kills glance-and-go, staff pick wrong button anyway. Reject as primary.
  - (c) **Shift-aware inference (recommended):** direction inferred from the staff member's rostered shift: punch within [shift_start − 2 h, shift_start + half of shift] → IN; within [midpoint, shift_end + 4 h] → OUT; punches <5 min after the previous one are deduplicated (treated as the same punch, screen shows the earlier result). The result screen shows the inferred direction big and bold with a 3-second **"Wrong? Tap to switch OUT↔IN"** override button. Overrides are logged.
- Store every punch as a raw timestamped event; IN/OUT pairing is a server-side interpretation that admins can re-run after corrections — never destroy the raw event.

## 6. Shift Management

- **Shift master:** `shift(id, name, start_time, end_time, crosses_midnight bool, grace_in_mins=10, early_out_grace_mins=10, half_day_below_hours, full_day_min_hours, paid_break_mins)`. Seed defaults for Indian hospital pattern: Morning 07:00-14:00, Evening 14:00-21:00, **Night 21:00-07:00 (crosses_midnight=true)**, General 09:00-17:00 (admin/OPD staff), plus 12-h variants if used.
- **Roster:** `roster_entry(staff_id, date, shift_id | 'WO' | 'LEAVE' | 'HOLIDAY')` — materialized per-person-per-date. Admin UI: monthly grid (staff × days), bulk tools: apply weekly rotation pattern (e.g., M-M-M-E-E-E-N-N-N-WO cycles common in nursing), copy-last-week, drag-fill. Weekly off configurable per person (nurses' WOs are staggered, not Sundays). v1 keeps rotation as bulk-apply templates, not an auto-scheduler.
- **Attendance derivation rules (nightly job + on-demand):** late = first IN > shift_start + grace (count + minutes); early-out = last OUT < shift_end − grace; half-day = worked_hours < half_day_below_hours (e.g., <4 h on an 8-h shift); status codes: P / A / L(late-P) / HD / WO / H / CL/SL/EL / OD(on-duty out). Three lates = half-day deduction is a common Indian policy — make it a configurable rule, off by default.
- **Midnight-crossing night shift — the correct model:** every roster entry spawns a `shift_instance(id, staff_id, sched_start_ts, sched_end_ts)` with **absolute timestamps** (2026-07-02 21:00 → 2026-07-03 07:00). Raw punches (epoch timestamps) are attributed to the shift_instance whose [start − 3 h, end + 4 h] window they fall in — **never to a calendar date directly**. The attendance register shows the night shift under its **start date** (industry convention; state it in the payroll export legend). An OUT at 07:05 on July 3 therefore correctly credits July 2's night shift, and the July-3 morning-shift person punching IN at 06:55 is disambiguated by their own roster.
- **Missed OUT punch (very common):** auto-close at shift_end + 4 h with `hours=scheduled`, status flagged `MISSING_OUT` → appears in admin regularization queue; admin fixes with reason (audit-logged). Same for missed IN.

## 7. Admin Dashboards & Reports

- **Live board ("Who is in right now"):** grid/list grouped by department, green=in, grey=out, count badges (Nurses 12/14 in). Auto-refresh via WebSocket/SSE. Useful for night-supervisor and fire-muster.
- **Today view:** present / absent (rostered but no punch by start+grace, excluding WO/leave) / latecomers with minutes late / on leave / PIN-fallback & low-confidence exceptions with punch photos.
- **Monthly register:** staff × days matrix with status codes, per-person totals (present days, paid days, lates, OT hours if enabled), filter by department/shift.
- **Payroll export:** `.xlsx` (openpyxl server-side): one row per staff — emp_code, name, department, days_present, half_days, paid_leave by type, unpaid/LOP, week_offs, holidays, total_payable_days, late_count, remarks. Also raw punch log export (CSV) for the accountant. Format finalized with whoever runs payroll before build.
- **Manual correction:** admin edits derived attendance (not raw punches); every correction stores before/after, actor, timestamp, mandatory reason in an **append-only `attendance_audit` table**; corrected cells visually marked in the register.
- **Leave (basic v1):** leave types with annual balances (CL/SL/EL configurable); request entered by staff from any LAN browser (phone on hospital Wi-Fi, login = emp_code + PIN) or by admin on their behalf; single-step approve/reject; approved leave auto-populates roster; balance ledger. No multi-level approval chains in v1.

## 8. India DPDP Act 2023 Obligations (employee biometrics)

- **Legal posture:** facial embeddings and photos are personal data under DPDP Act 2023 (DPDP Rules notified 2025, phased compliance underway). Although §7(i) "legitimate uses" covers some employment processing, biometric attendance should run on **explicit informed consent** — it's the defensible reading and costs little.
- **Consent capture (build into enrollment):** notice + consent screen in English/Hindi + local language stating: what is collected (face images → mathematical templates), purpose (attendance only), retention, who can see it (admin), right to withdraw. Digital acceptance recorded (staff_id, timestamp, notice version) + one signed paper form filed. **Consent must be genuinely optional: staff who decline use PIN-only attendance with no adverse consequence** — this is also your practical answer to withdrawal.
- **Data minimization:** store embeddings + 1 reference photo per person, not raw enrollment videos. Note honestly: embeddings are still personal data (re-identifiable within your gallery), so they get the same protection — but they can't be reversed into a portable photo, which materially lowers breach harm. Punch thumbnails: 30-day rolling retention, then hard-delete.
- **Deletion on exit:** offboarding checklist auto-task — delete embeddings, reference photo, and punch thumbnails within **30 days of full-and-final settlement**; retain non-biometric attendance records (dates, hours, status) for **3 years** (Shops & Establishments / payroll statutory retention). Log the deletion event.
- **Security duties:** encrypt DB at rest (SQLCipher or filesystem-level), embeddings table access restricted to the recognition service, TLS on LAN API, cloud backups encrypted client-side before upload (already in deployment plan — ensure biometric tables are included in encryption scope). Breach notification duty to the Data Protection Board and affected staff exists — keep an incident note template.
- **Consent registry screen** in admin: per-staff consent status (granted/declined/withdrawn, date, notice version) so an audit is a one-click export.

## 9. Hardware

- **Kiosk tablet (recommended): Samsung Galaxy Tab A9+ or Lenovo Tab M10 (3rd gen) class** — Android 12+, ≥4 GB RAM, ≥5 MP front camera, ₹13-18k. Locked in single-app kiosk mode (Fully Kiosk Browser ~₹700/device, or Android screen pinning). Buy one spare.
  - **Option B:** purpose-built face terminal (e.g., Hikvision DS-K1T343 / ZKTeco SpeedFace, ₹15-30k) — built-in IR liveness (stronger anti-spoof) but closed SDK/cloud lock-in and clunky integration with your custom shift logic. Choose only if buddy-punching proves rampant.
- **Mounting:** camera center at **1.40 m** with 5-10° upward tilt (covers ~1.50-1.85 m standing height); vandal-resistant wall enclosure with cable channel; clear floor marking/footprint sticker at 0.5-0.8 m from the wall so face size is consistent.
- **Lighting:** ≥200 lux diffuse frontal light on the face; mount a small 4000K LED panel above/behind the tablet; **never position the kiosk facing a window/door** (backlight silhouettes are the #1 field failure). Test at night-shift hours (21:00, 07:00) before finalizing placement.
- **Connectivity:** **Ethernet preferred** — USB-C hub with gigabit Ethernet + PD passthrough charging (₹1.5-2.5k) so the tablet charges and talks on one cable; Wi-Fi (5 GHz, dedicated SSID) as fallback. Static IP or DHCP reservation for the kiosk and server.
- **Power cuts:** the tablet's internal battery is a free 4-8 h UPS — kiosk keeps running through any cut. Server must be on a 600-1000 VA UPS bridging to the hospital generator (also required by the rest of the HMS). **Store-and-forward on the kiosk app:** if the server is unreachable, capture frame + timestamp into a local SQLite queue, show "recorded — will sync" (recognition happens on sync); auto-replay when the server returns. Punch is never lost to a power/network blip.
- **Server sizing note for this module:** the already-planned LAN server needs no GPU; any modern 4-core+ CPU (i5/Ryzen 5, 16 GB RAM) covers recognition + HMS concurrently.