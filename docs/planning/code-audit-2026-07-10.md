# Code Audit & Hardening — 2026-07-10

Scope: full read of the Phase-0 + Phase-1 codebase, a 9-dimension multi-agent
review with adversarial verification, cross-checked against `PLAN.md` and the
`docs/planning/*` specs. Baseline before this pass: 30 tests green. After:
**44 tests green**, `check` clean, `check --deploy` clean (ERROR level),
migrations consistent.

All fixes below are on branch `hardening-audit-fixes`.

## Fixed in this pass

### Security & access control
- **Clinical-read RBAC (HIGH).** `visit_detail`, `visit_slip`, `patient_detail`
  and `patient_list` were `@login_required` only — any authenticated account
  (incl. `pharmacist`, self-service `staff`) could open any patient's chart /
  MLC data. Introduced `apps/accounts/permissions.py` with `CLINICAL_READ_ROLES`
  / `PATIENT_MANAGE_ROLES` and gated every read/write patient & visit view.
  New test: `test_clinical_chart_read_is_role_gated`.
- **PIN brute-force lockout (HIGH).** The 6-digit fast-switch PIN had no
  throttling. Added `failed_pin_attempts` / `pin_locked_until` to `User`, a
  5-strike → 5-minute lockout wired into `PinSwitchForm`, and reset-on-success.
  Tests: `PinLockoutTests`.
- **Secure-by-default deploy (HIGH).** `settings.py` now refuses to boot with
  `DEBUG=0` and a placeholder `SECRET_KEY`, and derives secure cookies /
  `SECURE_SSL_REDIRECT` / nosniff / referrer-policy / `X_FRAME_OPTIONS` from
  `DEBUG`. `docker-compose` forces `DJANGO_DEBUG=0` in the container regardless
  of `.env`, and CSRF origins are https-only. CI now runs a migration-drift
  guard and `check --deploy --fail-level ERROR`.
- **Account/prescriber audit trail (MED).** `auditlog` now covers `User`
  (secrets excluded) and `DoctorProfile`, so PIN resets, activation, staff
  flags, registration-number and prescribing-enable changes are logged.
- **Admin hard-delete blocked (MED).** `NoHardDeleteAdminMixin` disables delete
  on `Patient`, `Visit`, `VitalsRecord`, `Receipt`, `Appointment` — enforcing
  the "clinical data is soft-delete only, never hard-deleted" retention rule.
- **`must_change_pin` enforced (LOW).** New `ForcePinChangeMiddleware` holds a
  flagged user on Set-PIN. Test: `ForcePinChangeTests`.

### Correctness & concurrency
- **Queue priority inversion (HIGH).** `RESUMED (3)` outranked `EMERGENCY (2)`, so
  a resumed routine patient was called ahead of a flagged emergency. Reordered
  to `WALK_IN < APPOINTMENT < RESUMED < EMERGENCY`. Test:
  `test_emergency_outranks_resumed_hold`.
- **Single-consult invariant (MED).** `call_next` / `start_consult` now serialize
  on a per-doctor row lock and refuse a second concurrent consult; added a
  Postgres/SQLite partial unique constraint `uniq_one_in_consult_per_doctor_day`
  as defence-in-depth. Test: `test_call_next_refuses_second_concurrent_consult`.
- **`recall` state guard (MED).** `recall` no longer re-announces a completed /
  no-show visit or rewrites its `called_at`. Test:
  `test_recall_rejected_for_completed_visit`.
- **TOCTOU on transitions (MED).** `skip` / `hold` / `resume` / `mark_no_show`
  are now atomic, re-locking and re-checking state under `select_for_update`.
- **DOB registration crash (HIGH, pre-existing, newly found).** `PatientForm`
  used `self.instance.pk` to detect a saved patient, but a `Patient`'s UUID pk is
  populated by its field default even before save — so registering *any* patient
  by date-of-birth hit `AttributeError` on `created_at.date()`. Fixed to key off
  `created_at`. Tests: `test_minor_via_dob_requires_guardian`,
  `test_adult_via_dob_is_valid`.
- **Refund day-boundary (LOW).** Refund redirect now uses IST (`localtime`) so an
  early-morning refund lands in the correct daily register.

### Compliance / plan-alignment
- **Per-doctor revenue** added to the daily collection register (PLAN §4 "the
  first report the owner will ask for").
- **MLC watermark (MED).** OPD slip now prints a full diagonal
  "MEDICO-LEGAL CASE" watermark in addition to the corner badge.
- **Unknown patient forced to MLC (MED).** An `is_unknown` patient's visit is now
  always filed MLC (checkbox disabled at the desk) with mandatory MLC context.
  Test: `test_unknown_patient_visit_is_forced_to_mlc`.
- **Nothing-hardcoded (finding #7).** New admin-editable `HospitalProfile`
  singleton (name, Marathi name, address, phone, slip footer) + context
  processor; slip, TV board and base template now read from it.
- **Backup integrity (MED).** `backup-loop.sh` no longer lets a failed `pg_dump`
  masquerade as success (POSIX sh has no `pipefail`): it dumps to a temp file,
  checks `pg_dump`'s exit code, validates the gzip, publishes atomically, and
  prunes old backups only after a verified-good new one.
- **`soft_delete(by=...)`** now records who performed the deletion.

## Backlog built in the follow-up pass

The audit's plan-gap items were then implemented (commits after the hardening
commit):

| Item | Status | Note |
|---|---|---|
| Follow-up "due today / next 7 days" call list | **BUILT** | `Visit.followup_date` stored on completion; `opd:followup_list` view + nav link. |
| Doctor-absence live-queue redirect | **BUILT** | `opd:queue_redirect` re-issues an absent doctor's waiting patients fresh tokens under another doctor; in-consult/done left alone. |
| Thermal token print (ESC/POS) | **BUILT** (needs on-site printer) | `apps/opd/escpos.py` builds the raw ESC/POS stream; endpoint streams to a network printer (`OPD_THERMAL_PRINTER_HOST`, port 9100) or returns bytes for a spooler. Calibrate against the actual TVS/Epson unit. |
| TV MP3 announcements | **BUILT** (needs audio assets) | Board composes per-symbol MP3 clips (`static/announce/<lang>/<X>.mp3`) with a chime fallback; `OPD_ANNOUNCE_AUDIO` flag; `manage.py announcement_clips` lists the finite clip set to record. |
| i18n scaffolding | **BUILT** | `LocaleMiddleware`, `LOCALE_PATHS`, `en/hi/mr` `LANGUAGES`, i18n context processor, `{% trans %}` on nav. String catalogs (`makemessages`/`compilemessages`) still to be filled. |
| Nav role-gating | **BUILT** | `user_roles` context processor hides links a role can't use. |

## Still open (deliberately deferred)

| Item | Note |
|---|---|
| Doctor-absence **reschedule** | `cancel_day` cancels + call list and `queue_redirect` covers today's queue; a per-appointment reschedule flow is still pending. |
| Deferred-privacy-notice completion | `privacy_notice_deferred` is set for unknown patients but no screen completes the notice once identity is known. |
| Translation catalogs | i18n machinery is in; the `.po`/`.mo` message files are not yet generated/translated. |
| Thermal & audio hardware bring-up | The ESC/POS + MP3 code paths exist; they need the physical printer for calibration and the recorded/TTS MP3 clips. |

## Suggested next steps
1. Merge this branch after review; run the phased-cutover exit criteria in
   `PLAN.md §11`.
2. On-site: set `OPD_THERMAL_PRINTER_HOST`, calibrate the token slip, record the
   announcement clips (`manage.py announcement_clips`), set `OPD_ANNOUNCE_AUDIO=1`.
3. Fill translation catalogs and finish the appointment-reschedule +
   deferred-notice flows.
