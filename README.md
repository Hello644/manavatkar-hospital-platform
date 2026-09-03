# Manavatkar Hospital Platform

Phase 0 foundation for the hospital management platform described in `PLAN.md`.

## What is in this first slice

- Django 5.x project skeleton with server-rendered pages.
- Custom user model, role groups, doctor profile fields, and 6-digit PIN support.
- Patient registry with UHID generation, privacy-notice capture, minor guardian validation, and duplicate hints.
- Docker Compose scaffold for Django, PostgreSQL, Caddy, and a day-one database backup loop.
- GitHub Actions CI for Django checks and tests.

## Local development

Install Python 3.12, then:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for the public hospital website, and
`http://127.0.0.1:8000/dashboard/` for the staff application.

## Public website vs. clinical system

`/` is the public hospital website (`apps.site`) — home, doctors, services,
contact, and online appointment booking that writes straight into the OPD list.
Everything else is the clinical system.

In production the two are served on **different hostnames from the same server**:

| Hostname               | Serves                    | Reachable from |
| ---------------------- | ------------------------- | -------------- |
| `manwatkarhospital.in` | public website only       | the internet   |
| `hms.hospital.lan`     | the whole clinical system | hospital LAN   |

A request arriving on a hostname listed in `PUBLIC_SITE_HOSTS` is refused
anything outside the public site — by Caddy's path allowlist, and again by
`apps.site.middleware.PublicSiteIsolationMiddleware`, so a proxy
misconfiguration alone cannot put patient records on the internet. Adding a
route to `config/urls.py` does **not** publish it.

Go-live steps, including the GoDaddy DNS records and what to do if the
hospital's line is behind CGNAT, are in
[`ops/deployment/go-live-manwatkarhospital.md`](ops/deployment/go-live-manwatkarhospital.md).

## Docker development / server

The container always runs with `DJANGO_DEBUG=0` (production posture), which turns
on secure cookies and TLS redirect and a guard that **refuses to boot with a
placeholder `SECRET_KEY`**. Before `docker compose up` set a real secret and DB
password in `.env`:

```bash
cp .env.example .env
# generate a real secret and paste it into DJANGO_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(64))"
# set POSTGRES_PASSWORD to something private, then:
docker compose up --build
```

The app is served through Caddy at `https://localhost/` (Caddy's internal CA for
`localhost`; a real domain gets Let's Encrypt). PostgreSQL dumps are written into
the `backup_data` volume by the backup sidecar, which verifies each dump and
prunes old backups only after a good new one exists.

## Security & audit

See [docs/planning/code-audit-2026-07-10.md](docs/planning/code-audit-2026-07-10.md)
for the hardening audit — access-control/RBAC, PIN lockout, deploy posture,
audit trail, queue-concurrency fixes — and the remaining Phase-1 backlog
(thermal print, MP3 announcements, follow-up call list, i18n scaffolding).

## Phase 0 notes

This is not yet a production deployment. On the hospital server, replace the simple dump loop with the planned pgBackRest/WAL pipeline and local encrypted disk setup before go-live.

