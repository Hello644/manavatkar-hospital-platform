from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.comms import services as comms_services
from apps.comms.models import OutboundMessage
from apps.core.models import HospitalProfile
from apps.opd.services import followups_due


class Command(BaseCommand):
    help = (
        "Queue follow-up reminders for visits due in the given window. "
        "Idempotent — safe to run daily (e.g. from cron)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=0,
            help="Window size in days from today (0 = today only).",
        )

    def handle(self, *args, **options):
        today = timezone.localdate()
        end = today + timedelta(days=options["days"])
        hospital = HospitalProfile.get_solo()
        queued = 0
        for visit in followups_due(today, end):
            patient = visit.patient
            if not patient.mobile:
                continue
            body = (
                f"{hospital.name}: {patient.full_name}, your follow-up with "
                f"{visit.doctor.display_name} is due on {visit.followup_date:%d-%b-%Y}."
            )
            msg = comms_services.queue_message(
                patient=patient,
                channel=settings.OPD_REMINDER_CHANNEL,
                to_number=patient.mobile,
                body=body,
                purpose=OutboundMessage.Purpose.FOLLOWUP,
                reference=f"followup:{visit.id}",
                scheduled_for=visit.followup_date,
            )
            if msg is not None:
                queued += 1
        self.stdout.write(self.style.SUCCESS(f"Queued {queued} follow-up reminder(s)."))
