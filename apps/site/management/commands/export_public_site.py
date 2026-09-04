"""Render the public website to static files for a CDN.

Why a static export rather than running Django on the host: the booking form
writes Patient and Appointment rows, so a deployment that could serve it would
need the clinical database beside it. Putting that in a cloud region reverses
the deployment decision recorded in ops/deployment/go-live-manwatkarhospital.md
— patient records stay on the hospital LAN. The exported site carries hospital
name, doctors, departments, notices and the OPD board, and nothing else.

Two things this command must get right, both enforced by tests:

  * It builds as if the request arrived on the public domain, so
    ``is_public_host`` is true and the staff sign-in link is left out. Exporting
    from a LAN-shaped request would publish the path to the clinical login on a
    CDN.
  * It builds with PUBLIC_BOOKING_ENABLED off, so the booking page shows the
    telephone instead of a form that would fail on submit.
"""

import json
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.test import Client, override_settings

# (url, path written under the output directory)
PAGES = [
    ("/", "index.html"),
    ("/doctors/", "doctors/index.html"),
    ("/services/", "services/index.html"),
    ("/contact/", "contact/index.html"),
    ("/book/", "book/index.html"),
    ("/robots.txt", "robots.txt"),
    ("/sitemap.xml", "sitemap.xml"),
]


class Command(BaseCommand):
    help = "Render the public website to static files."

    def add_arguments(self, parser):
        parser.add_argument("--out", default="dist", help="Output directory (default: dist).")
        parser.add_argument(
            "--host", default="manwatkarhospital.in",
            help="Public hostname to build as (default: manwatkarhospital.in).",
        )

    def handle(self, *args, **options):
        out = Path(options["out"])
        host = options["host"].lower()

        # The host's CLI keeps its project link inside the deploy directory.
        # Wiping the directory on rebuild would orphan it and create a brand new
        # project on every deploy, so carry it across.
        link = out / ".vercel"
        stashed = None
        if link.exists():
            stashed = Path(shutil.copytree(link, out.parent / ".vercel-stash",
                                           dirs_exist_ok=True))
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        if stashed:
            shutil.copytree(stashed, link, dirs_exist_ok=True)
            shutil.rmtree(stashed)

        overrides = {
            "PUBLIC_BOOKING_ENABLED": False,
            "PUBLIC_SITE_HOSTS": [host, f"www.{host}"],
            "ALLOWED_HOSTS": [host, f"www.{host}"],
            "DEBUG": True,          # plain /static/ URLs, no manifest needed
            "SECURE_SSL_REDIRECT": False,
        }
        with override_settings(**overrides):
            client = Client()
            for url, target in PAGES:
                response = client.get(url, HTTP_HOST=host, secure=True)
                if response.status_code != 200:
                    raise SystemExit(f"{url} returned {response.status_code}, refusing to publish")
                body = response.content.decode()
                self._guard(url, body)
                destination = out / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(body)
                self.stdout.write(f"  {url:<16} -> {target}")

        # Only the public stylesheet ships. Staff assets (the attendance kiosk
        # service worker and its manifest) stay off the CDN.
        css_out = out / "static" / "css"
        css_out.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(settings.BASE_DIR) / "static" / "css" / "site.css", css_out / "site.css")
        self.stdout.write("  static/css/site.css")

        # Config travels with the build so the deployed headers are reproducible
        # and reviewable in git, not clicked into a dashboard.
        (out / "vercel.json").write_text(json.dumps({
            "$schema": "https://openapi.vercel.sh/vercel.json",
            "cleanUrls": True,
            "trailingSlash": True,
            "headers": [{
                "source": "/(.*)",
                "headers": [
                    {"key": "Strict-Transport-Security",
                     "value": "max-age=31536000; includeSubDomains"},
                    {"key": "X-Content-Type-Options", "value": "nosniff"},
                    {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
                    {"key": "X-Frame-Options", "value": "DENY"},
                    {"key": "Permissions-Policy",
                     "value": "geolocation=(), microphone=(), camera=(), interest-cohort=()"},
                ],
            }],
        }, indent=2) + "\n")
        # Linking writes a short-lived OIDC token into the deploy directory.
        # Belt and braces: never upload dotfiles from here.
        (out / ".vercelignore").write_text(".env*\n.vercel/.env*\n")
        self.stdout.write("  vercel.json + .vercelignore")
        self.stdout.write(self.style.SUCCESS(f"Exported {len(PAGES)} pages to {out}/"))

    @staticmethod
    def _guard(url, body):
        """Refuse to write anything that leaks the clinical system."""
        forbidden = ["/login/", "/dashboard/", "/patients/", "/admin/", "/attendance/",
                     "Staff sign in", "csrfmiddlewaretoken"]
        for needle in forbidden:
            if needle in body:
                raise SystemExit(
                    f"{url} contains {needle!r}. The export must not publish anything "
                    "that points at the clinical system. Build aborted."
                )
