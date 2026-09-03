# Go live on manwatkarhospital.in

What this sets up:

```
                 internet                              hospital LAN
                    │                                        │
   manwatkarhospital.in                        hms.hospital.lan
   ─────────────────────                       ─────────────────
   public website only                         the whole clinical system
   home / doctors / services                   patients, OPD, Rx, lab,
   contact / book an appointment               pharmacy, attendance, admin
                    │                                        │
                    └──────────── one server ────────────────┘
```

Bookings made on the website land straight in the OPD appointment list, so
reception sees them next to the ones taken at the desk and over the phone.

**The clinical system is never published.** Two independent layers enforce it:
Caddy only proxies the public paths on the public domain, and Django's
`PublicSiteIsolationMiddleware` 404s everything outside the public site when a
request arrives on that hostname — even for a logged-in superuser. Test:
`apps/site/tests.py::PublicHostIsolationTests`.

---

## 0. Before anything: can this connection host a website?

Most Indian broadband lines are behind CGNAT, which means the hospital has no
public IP address and **port forwarding cannot work no matter how it is
configured**. Check this first — it decides everything below.

On the hospital's connection, run:

```bash
curl -s https://api.ipify.org; echo
```

Compare that to the WAN/Internet IP shown on the router's status page.

- **They match, and the address is not in `100.64.0.0/10`, `10.x`, `172.16–31.x`
  or `192.168.x`** → you have a public IP. Continue with **Path A**.
- **They differ, or the router shows a `100.64.x.x` address** → you are behind
  CGNAT. Either ask the ISP for a static public IP (Airtel/Jio/BSNL business
  plans offer one, typically ₹500–1500/month), or use **Path B**, which needs
  no public IP at all.

A dynamic public IP that changes on reconnect also works, with a dynamic-DNS
updater — but for a hospital, pay for the static IP. A website that disappears
after every power cut is worse than no website.

---

## 1. Server prerequisites

On the hospital server (Ubuntu 24.04, per `phase0-server-checklist.md`):

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
```

Give the server a **fixed LAN address** — either a static IP or a DHCP
reservation on the router. Everything below assumes `192.168.1.10`; substitute
the real one.

---

## 2. Configure the application

```bash
cd /opt/manwatkar-hospital
cp .env.example .env
```

Edit `.env`:

```ini
PUBLIC_DOMAIN=manwatkarhospital.in
LAN_HOSTNAME=hms.hospital.lan

DJANGO_SECRET_KEY=<paste the generated value>
POSTGRES_PASSWORD=<paste a generated password>
DJANGO_HSTS_SECONDS=31536000
```

Generate the two secrets — never reuse the placeholders, the app refuses to
boot with them:

```bash
python3 -c "import secrets; print('DJANGO_SECRET_KEY=' + secrets.token_urlsafe(64))"
```

```bash
python3 -c "import secrets; print('POSTGRES_PASSWORD=' + secrets.token_urlsafe(24))"
```

`docker-compose.yml` derives `DJANGO_ALLOWED_HOSTS`, `PUBLIC_SITE_HOSTS` and the
CSRF origins from those two hostnames — do not set them by hand on the server.

---

## 3. DNS at GoDaddy

The domain is registered at GoDaddy and is currently using GoDaddy's own
nameservers (`ns59.domaincontrol.com`, `ns60.domaincontrol.com`) with no A
record yet — so nothing resolves.

GoDaddy → **My Products** → `manwatkarhospital.in` → **DNS** → **Manage Zones**.

### Path A — you have a public IP

| Type  | Name  | Value                 | TTL    |
| ----- | ----- | --------------------- | ------ |
| A     | `@`   | your public IP        | 1 hour |
| CNAME | `www` | `manwatkarhospital.in`| 1 hour |

Delete GoDaddy's parked-page records first (the default `A @ → Parked` and any
`CNAME www → domain-name.com`), or they will conflict.

Then forward ports on the router: **80 → 192.168.1.10:80** and
**443 → 192.168.1.10:443**, TCP. Forward nothing else — in particular never
forward 8000, 5432 or 22 to the internet.

Wait for propagation, then verify from a machine **outside** the hospital
network (a phone on mobile data works):

```bash
dig +short manwatkarhospital.in
```

### Path B — behind CGNAT (no public IP)

Use a Cloudflare Tunnel. The server dials out to Cloudflare, so no public IP and
no port forwarding are needed, and the router stays completely closed.

1. Create a free Cloudflare account, add `manwatkarhospital.in` as a site.
2. Cloudflare gives you two nameservers. At GoDaddy → **DNS** →
   **Nameservers** → **Change** → **I'll use my own nameservers**, enter them.
   (This moves DNS control to Cloudflare; the domain stays registered at GoDaddy.)
3. On the server:

   ```bash
   curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared && sudo install cloudflared /usr/local/bin/
   ```

   ```bash
   cloudflared tunnel login && cloudflared tunnel create manwatkar-web
   ```

4. Route the hostname to the tunnel and point it at Caddy on the LAN:

   ```bash
   cloudflared tunnel route dns manwatkar-web manwatkarhospital.in
   ```

5. Run it as a service: `sudo cloudflared service install`.

With this path, **remove the `header` block's HSTS line from the `Caddyfile`**
only if Cloudflare terminates TLS with its own certificate and you see redirect
loops; otherwise leave it. Set the tunnel's origin to `http://localhost:80`.

Trade-off worth naming: your patients' traffic transits Cloudflare. That is
fine for a public brochure site and a booking form carrying a name and a phone
number. It is one more reason the clinical system stays off this path.

---

## 4. LAN name for staff

Staff must reach the clinical app at `https://hms.hospital.lan`. Point that name
at the server's LAN address in **one** of these ways:

- **Best** — on the router (DNS / "Local DNS" / "DNS Host Names" section): add
  `hms.hospital.lan → 192.168.1.10`. Every device gets it automatically.
- **Fallback** — on each staff PC, add to `/etc/hosts` (or
  `C:\Windows\System32\drivers\etc\hosts` on Windows):

  ```
  192.168.1.10  hms.hospital.lan
  ```

Do **not** create a public DNS record for it.

Caddy issues this hostname a certificate from its own local CA, so staff get a
browser warning until the CA is trusted once per device. Export it and install
it on staff machines:

```bash
docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt ./caddy-root.crt
```

On Windows: double-click → Install Certificate → Local Machine → Trusted Root
Certification Authorities. On Android tablets (the kiosk): Settings → Security →
Encryption & credentials → Install a certificate → CA certificate.

---

## 5. Start it

```bash
docker compose up -d --build
```

```bash
docker compose logs -f caddy
```

Watch for `certificate obtained successfully` for `manwatkarhospital.in`. If it
fails, ports 80/443 are not reaching the server — recheck step 3.

Create the first admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

---

## 6. Fill in the website content

Everything on the public site is admin-editable — no deploy needed to change a
phone number or add a service.

Sign in at `https://hms.hospital.lan/admin/` and set:

1. **Core → Hospital profile** — name, Marathi name, tagline, about text,
   address, city, pincode, phone, emergency number, WhatsApp, email, OPD hours,
   and `map_query` (paste the hospital's `lat,lng` from Google Maps for an
   accurate Directions link).
2. **Accounts → Doctor profiles** — for each doctor tick **Show on public
   website**, and **Accepts online booking** for the ones whose OPD slots
   patients may book themselves. Both are off by default, so no one is
   published by accident. Add qualifications and a short public bio.
3. **Public website → Services** — one row per department (Maternity, General
   Medicine, Pathology…). An emoji in `icon` renders as the card graphic.
4. **Public website → Announcements** — time-boxed notices for the home page.
   Set `ends_on` and they retire themselves.

---

## 7. Verify before you tell anyone the address

From **outside** the hospital network:

```bash
curl -sI https://manwatkarhospital.in | head -1
```

```bash
for p in /patients/ /opd/ /admin/ /login/ /dashboard/ /attendance/; do printf '%s -> ' "$p"; curl -s -o /dev/null -w '%{http_code}\n' "https://manwatkarhospital.in$p"; done
```

Every one of those must print **404**. If any returns 200 or 302, stop and fix
it before going further — that is patient data on the internet.

From **inside** the LAN, `https://hms.hospital.lan/dashboard/` should load the
staff login.

---

## 8. Daily maintenance

Add to the server's crontab (`sudo crontab -e`):

```cron
# Age out the public-booking abuse log (stores IPs — DPDP storage limitation).
30 2 * * * cd /opt/manwatkar-hospital && docker compose exec -T web python manage.py purge_booking_attempts
```

Backups already run in the `backup` container. Confirm files are appearing:

```bash
docker compose exec backup ls -lh /backups
```

---

## Known gaps — read before going live

- **No SMS OTP on the booking form.** Nothing proves the person booking owns the
  mobile number they typed. What protects the calendar instead: a honeypot
  field, 8 attempts/hour and 20/day per IP, 3 bookings/day per number, and at
  most 2 open appointments per number (`apps/site/throttle.py`). Reception
  should still glance at the day's website bookings. Closing this properly means
  wiring an SMS gateway into `apps.comms` and adding an OTP step — worth doing
  if abuse ever shows up in **Public website → Public booking attempts**.
- **Website bookings create provisional patient records** — flagged
  `is_unknown`, with consent deferred. Reception must complete identity, age,
  sex and the DPDP privacy notice when the patient arrives. They appear in the
  appointment list like any other booking, with "Booked by website" in the notes.
- **Online booking uses fixed OPD windows** (10:00–13:00, 17:00–20:00, from
  `apps/opd/booking.py`), and does not know about leave, surgery lists or
  holidays. Until a doctor-availability calendar exists, untick **Accepts online
  booking** for a doctor before their leave, or expect to phone those patients.
- **Bookings are capped at 30 days ahead** (`MAX_ADVANCE_DAYS`).
- **The public site has no cancel/reschedule flow.** The confirmation page tells
  patients to call. Reception cancels in the appointment list.
- **HSTS is set to one year** by `DJANGO_HSTS_SECONDS`. Once browsers have seen
  it, `manwatkarhospital.in` is HTTPS-only for them for a year — correct, but
  it means a broken certificate becomes a hard outage rather than a warning.
  Keep an eye on the Caddy renewal logs.
- **The AI phone receptionist stays off** (`VOICE_AGENT_ENABLED` unset). When it
  is switched on, its three webhook routes — and only those, not the call log —
  become reachable on the public domain, and they verify a Twilio HMAC
  signature. Setting `VOICE_AGENT_ENABLED=1` without `TWILIO_AUTH_TOKEN` refuses
  to boot.
