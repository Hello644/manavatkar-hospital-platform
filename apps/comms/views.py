from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import FRONT_DESK_ROLES, role_required
from apps.core.models import HospitalProfile
from apps.prescriptions.models import Drug, Prescription

from . import services
from .models import OutboundMessage


def _share_block_reason(rx):
    """WhatsApp sharing is blocked for MLC documents and Schedule-X drugs
    (PLAN §5 / decision log #1)."""
    if rx.visit and rx.visit.is_mlc:
        return "This is a medico-legal case — digital sharing is blocked."
    if any(item.drug and item.drug.schedule == Drug.Schedule.X for item in rx.items.all()):
        return "Contains a Schedule X drug — digital sharing is blocked."
    return ""


@role_required(*FRONT_DESK_ROLES)
def share_prescription(request, pk):
    rx = get_object_or_404(
        Prescription.objects.select_related("patient", "doctor", "visit").prefetch_related(
            "items__drug"
        ),
        pk=pk,
    )
    block_reason = _share_block_reason(rx)

    if request.method == "POST":
        if block_reason:
            services.log_message(
                patient=rx.patient, channel=OutboundMessage.Channel.WHATSAPP,
                to_number=request.POST.get("number", ""), body="(blocked)",
                purpose=OutboundMessage.Purpose.RECORD_COPY,
                status=OutboundMessage.Status.BLOCKED, user=request.user, error=block_reason,
            )
            messages.error(request, block_reason)
            return redirect("prescriptions:detail", pk=rx.pk)

        number = services.normalize_msisdn(request.POST.get("number", ""))
        if len(number) != 10 or request.POST.get("confirm") != "yes":
            messages.warning(request, "Confirm a valid 10-digit destination number.")
            return redirect("comms:share_prescription", pk=rx.pk)

        text = services.record_copy_text(rx, HospitalProfile.get_solo())
        services.log_message(
            patient=rx.patient, channel=OutboundMessage.Channel.WHATSAPP, to_number=number,
            body=text, purpose=OutboundMessage.Purpose.RECORD_COPY,
            status=OutboundMessage.Status.SENT, user=request.user,
        )
        # Opens WhatsApp with the confirmed number + record-copy text; the front
        # desk attaches the printed PDF in the chat.
        return HttpResponseRedirect(services.whatsapp_link(number, text))

    return render(
        request,
        "comms/share_prescription.html",
        {"rx": rx, "block_reason": block_reason},
    )


@role_required(*FRONT_DESK_ROLES)
def outbox(request):
    return render(
        request,
        "comms/outbox.html",
        {"messages_list": OutboundMessage.objects.select_related("patient")[:100]},
    )
