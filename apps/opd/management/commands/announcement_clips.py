from django.conf import settings
from django.core.management.base import BaseCommand

from apps.accounts.models import DoctorProfile
from apps.opd.services import token_prefix


class Command(BaseCommand):
    help = (
        "List the MP3 announcement clips the TV board needs "
        "(static/announce/<lang>/<SYMBOL>.mp3)."
    )

    def handle(self, *args, **options):
        prefixes = {token_prefix(d) for d in DoctorProfile.objects.all()} | {"T"}
        symbols = sorted(set("0123456789") | {p for p in prefixes if p})
        langs = [code for code, _label in settings.LANGUAGES]

        self.stdout.write(
            "Generate one short MP3 per symbol per language (TTS of the letter/number):"
        )
        for lang in langs:
            for symbol in symbols:
                self.stdout.write(f"static/announce/{lang}/{symbol}.mp3")
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(symbols)} symbols x {len(langs)} languages = "
                f"{len(symbols) * len(langs)} clips"
            )
        )
