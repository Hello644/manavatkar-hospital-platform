# Phase 0 Server Checklist

Use this checklist for the physical hospital server work.

## Hardware

- Primary mini-PC installed in the locked network cabinet.
- Ubuntu Server 24.04 LTS installed.
- Data disk encrypted with LUKS.
- UPS connected and graceful shutdown configured.
- Server, switch, router, and access points labelled.

## Network

- Server on fixed LAN address.
- Staff devices on trusted LAN or staff Wi-Fi.
- Patient/guest Wi-Fi isolated from the server.
- Real domain purchased.
- Split-horizon DNS configured for the app hostname.

## Application

- `.env` created from `.env.example`.
- Strong `DJANGO_SECRET_KEY` and PostgreSQL password set.
- `docker compose up -d --build` completes.
- Admin user created.
- Role groups present in admin.
- First backup file appears in the backup volume.

## Before Real Use

- Replace dump-only backup with pgBackRest and WAL archiving.
- Configure Caddy DNS-01 TLS for the real domain.
- Document restore and rollback steps.
- Run a restore drill on the standby mini-PC.

