from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


FRONT_DESK_ROLES = ("receptionist", "admin")
NURSE_ROLES = ("nurse", "admin")
DOCTOR_ROLES = ("doctor", "admin")
REPORT_ROLES = ("receptionist", "admin")


def user_in_roles(user, roles):
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
