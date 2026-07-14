from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render

from apps.accounts.permissions import DOCTOR_ROLES, role_required, user_in_roles
from apps.opd.models import Visit

from . import services
from .models import AiInteraction


@role_required(*DOCTOR_ROLES)
def assist_visit(request, pk, task):
    visit = get_object_or_404(Visit.objects.select_related("patient", "doctor"), pk=pk)
    profile = getattr(request.user, "doctor_profile", None)
    is_admin = user_in_roles(request.user, ("admin",)) or request.user.is_superuser
    if not is_admin and (profile is None or visit.doctor_id != profile.pk):
        raise PermissionDenied
    if task not in AiInteraction.Task.values:
        raise PermissionDenied

    ctx = {"visit": visit, "task": task, "available": services.is_available()}
    if not ctx["available"]:
        ctx["message"] = (
            "AI assistant is not configured. Set OPD_AI_ENABLED=1 and an Anthropic "
            "API key to enable it."
        )
        return render(request, "assist/result.html", ctx)

    context_text = services.build_context(visit)
    ok, output = services.run(task, context_text)
    ctx["output"] = output
    ctx["ok"] = ok
    if ok:
        from django.conf import settings

        AiInteraction.objects.create(
            visit=visit, task=task, model=settings.OPD_AI_MODEL,
            output=output, created_by=request.user,
        )
    else:
        messages.warning(request, output)
    return render(request, "assist/result.html", ctx)
