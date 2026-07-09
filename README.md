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

Open `http://127.0.0.1:8000/`.

## Docker development

Install Docker, then:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The app is served through Caddy at `http://localhost/`. PostgreSQL dumps are written into the `backup_data` Docker volume by the backup sidecar.

## Phase 0 notes

This is not yet a production deployment. On the hospital server, replace the simple dump loop with the planned pgBackRest/WAL pipeline and local encrypted disk setup before go-live.

