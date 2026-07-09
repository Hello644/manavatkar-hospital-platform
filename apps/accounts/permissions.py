"""Central role definitions and access-control decorators.

Roles are Django groups seeded in ``apps.accounts.signals``. Keeping the role
sets and the ``role_required`` gate in the base ``accounts`` app lets every
other app (patients, opd, ...) import from one place without a layering cycle.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


# Individual roles
ADMIN = "admin"
DOCTOR = "doctor"
NURSE = "nurse"
RECEPTIONIST = "receptionist"
PHARMACIST = "pharmacist"
STAFF = "staff"

# Task-oriented role sets. ``admin`` is included everywhere clinical/desk staff
# can act; superusers always pass (see ``user_in_roles``).
FRONT_DESK_ROLES = (RECEPTIONIST, ADMIN)
NURSE_ROLES = (NURSE, ADMIN)
DOCTOR_ROLES = (DOCTOR, ADMIN)
REPORT_ROLES = (RECEPTIONIST, ADMIN)

# Who may READ a patient's identity / clinical chart / OPD slip. Deliberately
# excludes ``pharmacist`` (read-only on Rx only, Phase 2) and ``staff``
# (self-service leave/attendance) — they have no chart-read purpose (DPDP
# data-minimisation / need-to-know).
CLINICAL_READ_ROLES = (DOCTOR, NURSE, RECEPTIONIST, ADMIN)

# Who may create/edit the patient registry.
PATIENT_MANAGE_ROLES = (RECEPTIONIST, ADMIN)


def user_in_roles(user, roles):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name__in=roles).exists()


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not user_in_roles(request.user, roles):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
