from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.attendance.models import PunchEvent


class Command(BaseCommand):
    help = (
        "Hard-delete punch photos older than ATTENDANCE_PHOTO_RETENTION_DAYS "
        "(DPDP: photos purged after 45 days). Punch records themselves are kept."
    )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=settings.ATTENDANCE_PHOTO_RETENTION_DAYS)
        purged = 0
        for punch in PunchEvent.objects.filter(created_at__lt=cutoff).exclude(photo=""):
            if punch.photo:
                punch.photo.delete(save=False)
                punch.photo = None
                punch.save(update_fields=["photo"])
                purged += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Purged {purged} punch photo(s) older than "
                f"{settings.ATTENDANCE_PHOTO_RETENTION_DAYS} days."
            )
        )
