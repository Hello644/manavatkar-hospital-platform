"""Age out the public-booking abuse log.

The log stores source IP addresses, which are personal data under the DPDP Act
2023. They are kept only as long as they are useful for spotting abuse, then
deleted — data minimisation and storage limitation. Run daily from cron:

    docker compose exec -T web python manage.py purge_booking_attempts

This is a genuine hard delete, unlike clinical records, which are only ever
soft-deleted. A security log is not a medical record.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.site.models import PublicBookingAttempt


class Command(BaseCommand):
    help = "Delete public booking attempts older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=PublicBookingAttempt.RETENTION_DAYS,
            help=f"Retention window (default {PublicBookingAttempt.RETENTION_DAYS}).",
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Report what would be deleted."
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        stale = PublicBookingAttempt.objects.filter(created_at__lt=cutoff)
        count = stale.count()
        if options["dry_run"]:
            self.stdout.write(f"Would delete {count} attempt(s) older than {cutoff:%Y-%m-%d}.")
            return
        stale.delete()
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {count} attempt(s) older than {cutoff:%Y-%m-%d}.")
        )
