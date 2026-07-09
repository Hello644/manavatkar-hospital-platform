# Clinical/OPD & Prescriptions — Functional Specification (v1)

## 1. Patient Registry

### 1.1 Fields
**Mandatory (registration must complete in <60s at front desk):**
- `uhid` (system-generated, immutable)
- `full_name` (single field; store `name_normalized` lowercase/trimmed for search)
- `mobile` (10-digit, normalized via libphonenumber; allow "no phone" flag for elderly/dependents)
- `age` OR `dob` (age-entry auto-computes approximate DOB `YYYY-07-01`; flag `dob_estimated=true`)
- `sex` (M/F/Other)

**Optional (collectable later, never block registration):**
- `address_line`, `area/village`, `city`, `district`, `pincode`
- `abha_number` (14-digit Ayushman Bharat Health Account — free-text field in v1, ABDM integration deferred; storing it now future-proofs Scan & Share)
- `blood_group`, `email`, `aadhaar_last4` (never full Aadhaar — avoids DPDP Act 2023 exposure)
- `allergies[]` (structured: substance + reaction + severity; also free-text note)
- `chronic_conditions[]` (tag list: DM, HTN, asthma, CKD, epilepsy, pregnancy…)
- `photo` (webcam capture, optional), `preferred_language` (for Rx instruction snippets)
- `emergency_contact_name/phone`, `referral_source`
- Audit: `created_at`, `created_by`, `updated_at`, soft-delete/merge fields

### 1.2 UHID scheme
Options:
1. **Pure sequential** (`000123`) — trivial, but leaks patient volume and collides if hospital ever federates.
2. **Year-prefixed sequential + check digit** (`RHM-26-004217-3`, Luhn mod-10 check digit) — human-readable over phone, typo-detectable, sortable.
3. ABHA as primary ID — rejected: requires internet + patient consent flow, many patients won't have one.

**Recommendation: option 2.** 3-letter hospital code + 2-digit year + 6-digit sequence + Luhn check digit. Print as barcode/QR (Code-128) on OPD slip and Rx so any station can scan instead of typing.

### 1.3 Duplicate detection
- On registration, before save, run: (a) exact mobile match, (b) trigram similarity on `name_normalized` (Postgres `pg_trgm`, threshold 0.55) combined with age ±3y and same sex.
- Show "Possible existing patients" panel with one-click "Use this patient" — desk staff decides; never auto-merge.
- Admin-only **merge tool**: pick survivor UHID, re-point visits/Rx, keep tombstone record with `merged_into` for old UHID (old barcode still resolves).

### 1.4 Search
- Single omnibox: digits ≥6 → phone/UHID search; text → name trigram + prefix search; barcode scan → direct UHID hit.
- Results show name, age/sex, area, last visit date, family members. Target <300 ms on 100k records (index: `mobile`, `gin(name_normalized gin_trgm_ops)`).

### 1.5 Family linking
- `family_id` (nullable) + `relationship_to_head`. Trigger: when a new registration reuses an existing mobile, prompt "2 patients share 98220xxxxx — link as family?"
- Family view on patient screen (front desk can register a child in ~20s by copying address/phone from family head). No shared clinical data — linking is administrative only.

## 2. OPD Flow

### 2.1 Paths
- **Walk-in:** search/register patient → select doctor → pay consult fee (record fee + mode: cash/UPI; a printed OPD slip with token, doctor, fee receipt no.) → token issued.
- **Appointment:** front-desk books slot (phone call or in-person); v1 has **no patient-facing portal** (server is LAN-only). Slot grid per doctor per day (configurable slot length, default 10 min, capacity per slot 1–2). On arrival, "Check-in" converts appointment → token.
- Appointment states: `booked → checked_in → in_consult → completed / no_show / cancelled`.

### 2.2 Token/queue mechanics
- **Per-doctor, per-day queues.** Token format `A-042` (doctor room letter + daily sequence). Reset nightly.
- Priority interleaving rule (simple, explainable): a checked-in **appointment** patient is inserted ahead of walk-ins but never preempts the patient already called; walk-ins otherwise FIFO. Optional `emergency` flag jumps to front (audit-logged).
- Queue actions at nurse/doctor station: **Call next / Recall (re-announce) / Skip (patient absent → drops 3 positions, 2 skips → parked) / Hold (sent for ECG/lab, returns to front on "resume") / Complete**.
- **Waiting-area display:** any cheap Android TV / HDMI stick opening a full-screen browser URL (`/display/opd`). Shows per-doctor: "Now serving A-041", next 3 tokens, doctor status (In / Break / Arriving). Updates via WebSocket (<2s). Audio announcement via browser TTS (Web Speech API) in Hindi + one configurable regional language (e.g., Marathi): "Token A-42, Room 1". Estimated wait = rolling average consult time (last 10 consults) × queue position.

### 2.3 Vitals capture (nurse station, before doctor)
Fields: weight (kg, mandatory for age <12), height (cm), auto-BMI, BP sys/dia, pulse, SpO₂, temperature (°F), RBS (optional), pain score (0–10, optional), LMP (if female 12–50), **chief complaint** (free text, 1 line), allergy-review prompt ("Allergies on file: penicillin — still correct?"). Vitals entry moves patient to state `vitals_done`; doctor's queue shows a green dot. Out-of-range values highlight (e.g., SpO₂ <94, BP >160/100) but never block.

### 2.4 Doctor consultation screen (single screen, keyboard-first)
- **Left rail (read-only context):** patient header (name, age/sex, UHID, family), **allergies in red banner**, chronic condition tags, today's vitals with deltas vs last visit, last 3 visits as one-liners (`12-Jun-26 · Dr. A · Acute pharyngitis · Amox+PCM ×5d`) — click expands full past Rx; "repeat this Rx" button on each.
- **Center:** diagnosis field (ICD-10 autocomplete on common ~500 codes + free text; ICD coding optional, never mandatory) + Rx composer (§3).
- **Bottom strip:** advice, investigations, follow-up chips, referral note.
- Doctor actions end the visit: **Print & Next** (one keystroke, Ctrl+P) → prints Rx, marks token complete, auto-calls next token.

### 2.5 Follow-up
- Chips: +3d / +1w / +2w / +1m / custom date. Prints on Rx ("Review on 09-Jul-2026"). Creates a `followup_due` record (not a hard slot booking).
- Front-desk dashboard: "Follow-ups due today/this week" with call list. Optional WhatsApp/SMS reminder T-1 day via queued outbox (sends when internet is up; silently skips if offline >48h).

## 3. Prescription Authoring (target: 45–90 s per Rx)

### 3.1 Composer mechanics
Grid rows, one drug per row, fully keyboard-driven (Enter = next field, Ctrl+Enter = new row):
`Drug | Dose | Frequency | Duration | Food relation | Instruction | Qty (auto)`
- **Drug autocomplete:** fires at 2 chars, searches brand + generic + phonetic index; ranks by (1) this doctor's usage frequency, (2) hospital-wide frequency. Shows schedule badge (H/H1/X) and strength inline. Free-text fallback row ("unlisted drug") so the doctor is never blocked; unlisted entries land in an admin "add to formulary" queue.
- **Dosage shorthand:** accept `1-0-1`, `1/2-0-1/2`, `1-1-1-1` (QID), and codes OD/BD/TDS/QID/HS/SOS/STAT — parser normalizes to structured frequency. Typing `1-0-1 x 5` in one field fills frequency + duration.
- **Duration:** `5d / 2w / 1m / cont` (continuous for chronics). **Qty auto-computed** (freq/day × days, rounded to strip size if defined).
- **Per-doctor favorites:** star any drug-with-default-signature (e.g., "PCM 650 · 1-0-1 · 3d · after food"); favorites panel = top-20 one-click inserts. Auto-learned defaults: last-used signature per drug per doctor pre-fills.
- **Diagnosis templates ("Rx sets"):** named bundles (e.g., "Acute GE – adult" = ORS + Ondansetron + Zinc + diet advice + "review if…"), owned per-doctor with hospital-shared library; inserting a set populates all rows, each still editable. Templates can also carry advice/investigations. Target: template-based Rx signed in <30 s.

### 3.2 Instructions & local language
- Per-row instruction picker: curated **snippet library stored in 3 renderings** — English, Hindi, regional language (configurable per install; e.g., Marathi). Snippets keyed to structure, e.g., frequency `1-0-1` + after-food auto-suggests "सकाळ-संध्याकाळ जेवणानंतर १ गोळी". ~60 seed snippets (frequencies × food relations × common forms: tablet/syrup/drops/inhaler/insulin/ointment).
- Rx prints drug lines with the patient's `preferred_language` instruction under each drug in larger font; clinical shorthand (1-0-1) stays for the pharmacist.

### 3.3 Advice / Investigations sections
- **Investigations:** autocomplete over ~150-item local lab/radiology list (CBC, RBS, HbA1c, X-ray chest PA…), prints as checklist block.
- **Advice:** free text + snippet chips ("plenty of oral fluids", "avoid oily food", also tri-lingual). Both are per-doctor-favoritable.

## 4. Indian Legal/Format Requirements on Printed Rx

Per Indian Medical Council (Professional Conduct, Etiquette and Ethics) Regulations 2002 (clause 1.5), Drugs & Cosmetics Rules 1945 (Rules 65, 97, Schedules H/H1/X), Pharmacy Practice Regulations 2015:
- **Header:** hospital name, full address, phone, registration/license no. (clinical establishment reg. where applicable), timings.
- **Doctor block:** name, qualifications (MBBS, MD…), **State Medical Council registration number + council name** (mandatory), speciality. Multi-doctor: header block is per-doctor, pulled from the doctor profile.
- **Patient block:** name, age, sex, UHID, date, weight (mandatory print for pediatric Rx).
- **Generic-name guidance (NMC):** clause 1.5 requires prescribing "as far as possible" in generic names, legibly, preferably capitals. (The stricter NMC RMP Regulations 2023 generic-only mandate was held in abeyance; treat as guidance, not hard block.) **Implementation: print `GENERIC NAME in caps` with brand in parentheses beneath — e.g., `TAB. PARACETAMOL 650 mg (Dolo 650)`.** Formulary stores both, so this is free.
- **Schedule annotations:** each drug row carries its schedule; if any **Schedule H1** drug present, print the mandated warning box: "Schedule H1 drug — Warning: To be sold by retail on the prescription of a Registered Medical Practitioner only" and system retains Rx record ≥3 years (pharmacy's H1 register duty, but hospital copy helps). **Schedule X**: print "Schedule X" prominently, force duration ≤ 30 days, and flag that the Rx must be in duplicate (print 2 copies automatically); block WhatsApp-only delivery for X drugs. NDPS drugs: out of v1 formulary scope by policy (documented exclusion).
- **Rx symbol (℞)**, footer "Not valid without signature", follow-up date, page `1/1`.
- **Signature/stamp:** **Recommendation: wet-ink signature + rubber stamp on the printed sheet is the legal instrument in v1.** The archived/WhatsApp PDF carries the doctor's typed name + reg. no. + line "Electronically generated prescription; signed original issued to patient." Do NOT paste scanned signature images by default (forgery risk on shared PDFs); offer it as a per-doctor opt-in toggle. Full DSC/eSign (IT Act digital signature) deferred — needs internet + per-signature cost.

## 5. Output Formats

- **Print:** default **A5 portrait** (fits standard Indian OPD pad look, halves paper cost); A4 selectable per doctor. Two letterhead modes per doctor/hospital: (a) **pre-printed letterhead** — configurable top margin in mm (e.g., 45 mm), system prints body only; (b) **plain paper** — system renders full header + optional logo. Rendering: server-side HTML→PDF via **headless Chromium (Puppeteer)** for pixel-identical output across the LAN's mixed browsers; sent to browser print dialog, or silent-print to a designated laser printer per consult room via a small print-agent (e.g., PDF → `SumatraPDF -print-to` on the room PC). Laser only — inkjet smudges, thermal fades (legal retention problem).
- **PDF archive:** the exact PDF generated at "Print & Next" is stored immutably (`/rx/2026/07/RHM-26-004217-3_V000891.pdf`) with SHA-256 hash + structured JSON of the Rx. Reprints watermark "DUPLICATE". Retention: indefinite (storage is cheap; H1 needs ≥3y anyway). Included in encrypted cloud backup set.
- **WhatsApp:** options — (1) **Meta WhatsApp Business Cloud API** via a BSP (Gupshup/Interakt/AiSensy, utility template ≈ ₹0.12–0.35/msg): fully automatic, needs approved template + internet; queue in an outbox table, worker sends when online. (2) **wa.me click-to-chat** from front-desk phone with manual PDF attach: zero cost, zero setup, manual. (3) Twilio: pricier, no India advantage. **Recommendation: ship (2) on day one (a "Share" screen shows QR + wa.me link and drops the PDF into a front-desk shared folder), build (1) as the v1.1 outbox once volumes justify.** Always also print — WhatsApp is a copy, never the primary artifact. Skip WhatsApp for Schedule X.

## 6. Drug Database for India

| Option | What it gives | Trade-offs |
|---|---|---|
| Public datasets: **NLEM 2022** (384 essential medicines), **Jan Aushadhi/PMBJP product list** (~1,965 generics + strengths + MRP, downloadable), CDSCO approved-drugs lists, **SNOMED CT (free for India via NRCeS/MoHFW)** | Free, legal, generic names + strengths | No Indian brand names, no dosing defaults, CDSCO data is messy PDFs; SNOMED is an ontology, not a dispensing list |
| Commercial APIs: CIMS/MIMS India, DrugBank, First Databank | Brands, interactions, curated | US$1k–10k+/yr licensing, internet-dependent APIs conflict with offline-first requirement, contract overhead absurd for one 30-bed hospital |
| Scraped 1mg/Netmeds/Kaggle dumps | Brands + prices | ToS/legal risk, stale, unmaintainable — **reject** |
| **Own formulary (300–800 SKUs)** | Exactly what this hospital prescribes; fields: generic (INN), brand, strength, form, route, schedule (H/H1/X/G/OTC), pack size, default adult signature, pediatric mg/kg + max where applicable, tri-lingual instruction hint | 2–4 days of one-time pharmacist+doctor curation; new drugs need manual add (mitigated by free-text fallback + admin add-queue) |

**Recommendation: own formulary.** Seed script imports NLEM + Jan Aushadhi CSVs for generics/strengths, then the hospital pharmacist maps the pharmacy purchase register's brands onto them (spreadsheet import supported). Reality check: a small hospital's doctors prescribe from a pool of ~200–400 drugs; a curated small list beats a noisy 300k-row national list for autocomplete quality and safety-flag accuracy.

## 7. Safety Features — v1 vs Deferred

**v1 (realistic, high-value, low-liability):**
- **Allergy hard-check:** ingredient-level match of composer rows against patient allergy list (formulary stores ingredient(s) per SKU, so "penicillin" allergy catches Amoxiclav brand). Blocking modal with typed override reason (logged).
- **Duplicate-ingredient warning:** two rows sharing an ingredient (classic: PCM in two brands).
- **Max-dose flags for a curated ~30-drug list** (paracetamol 4 g/day adult, 60 mg/kg/day pediatric, etc.) — warn, never block.
- Pediatric weight-missing block: cannot sign a Rx for age <12 without today's weight.
- Schedule-based prompts (H1 warning box, X duration cap) as in §4.

**Deferred (v2+, requires licensed knowledge base and real curation):** full drug–drug interaction engine, pregnancy/lactation categories, renal/hepatic dose adjustment, drug–disease contraindications. Explicitly print nothing that implies interaction checking was done.

## 8. Edge Cases

- **Pediatric dosing:** for formulary drugs with `mg_per_kg` defined, composer shows inline calculator: weight (from today's vitals) × mg/kg → suggested dose + nearest syrup ml (formulary stores mg/ml concentrations); doctor confirms/edits — suggestion, never auto-fill silently. Weight and computed mg/kg print on the Rx.
- **Refills/repeat Rx:** "Repeat" clones a past Rx into the composer as a fresh dated Rx (never re-issue the old PDF). Chronic patients: front-desk-initiated "refill request" queue that the doctor approves in one click (still generates a doctor-signed consult record, fee configurable/zero). H1 repeats allowed with doctor action; Schedule X never repeatable without full consult.
- **Multiple doctors:** everything doctor-scoped — favorites, templates, default paper size, letterhead block, reg. number, consult fee, queue. Concurrent OPDs are independent queues on one display.
- **Locum doctors:** time-boxed user accounts (`valid_from/valid_to`, auto-disable) requiring their own name, qualification, and **their own SMC registration number** before first Rx (hard validation — a locum must never print under the owner's registration). Rx attributed to locum in archive/reports; locum cannot edit formulary or templates marked hospital-shared.
- **In-hospital injections/administrations:** composer row type `Administer in OPD` (inj/nebulization/dressing). On sign, creates a **nurse administration task**: nurse records batch no., expiry, route/site, time, administered-by; task completion stamps the visit record. Rx prints these rows under a separate "Administered in hospital" section (so the pharmacy doesn't dispense them again). Stat-emergency path: nurse can back-record with doctor co-sign.
- **Misc:** patient leaves before consult → token `no_show`, fee refund flag; power/browser crash mid-Rx → composer autosaves draft every 5 s keyed to visit; doctor edits after print → new Rx version, old PDF marked superseded, reprint says "REVISED".

**Cross-module contracts for the synthesizer:** patient registry is the single shared entity (attendance module is staff-only, no overlap); visit/token events feed the admin dashboard; all Rx PDFs + DB in the encrypted cloud-backup set; waiting display and TTS run entirely on LAN (no internet dependency); WhatsApp/reminder outbox is the only internet-touching clinical feature and must degrade silently.