from .models import HospitalProfile


def hospital(request):
    """Expose the editable hospital identity to every template as ``hospital``."""
    return {"hospital": HospitalProfile.get_solo()}


def user_roles(request):
    """Role booleans for nav gating so links a role can't use are hidden."""
    user = getattr(request, "user", None)
    ctx = {
        "is_admin_role": False,
        "is_doctor_role": False,
        "is_nurse_role": False,
        "is_receptionist_role": False,
        "is_pharmacist_role": False,
        "is_clinical_role": False,
    }
    if user is not None and user.is_authenticated:
        names = set(user.groups.values_list("name", flat=True))
        su = user.is_superuser
        ctx["is_admin_role"] = su or "admin" in names
        ctx["is_doctor_role"] = su or "doctor" in names
        ctx["is_nurse_role"] = su or "nurse" in names
        ctx["is_receptionist_role"] = su or "receptionist" in names
        ctx["is_pharmacist_role"] = su or "pharmacist" in names
        ctx["is_clinical_role"] = su or bool(
            names & {"doctor", "nurse", "receptionist", "admin"}
        )
    return ctx
