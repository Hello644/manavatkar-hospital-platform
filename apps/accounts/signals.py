from django.contrib.auth.models import Group
from django.db import DEFAULT_DB_ALIAS, OperationalError, ProgrammingError
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ROLE_NAMES = [
    "admin",
    "doctor",
    "nurse",
    "receptionist",
    "pharmacist",
    "staff",
]


@receiver(post_migrate, dispatch_uid="accounts.ensure_role_groups")
def ensure_role_groups(sender, using=DEFAULT_DB_ALIAS, **kwargs):
    try:
        for role_name in ROLE_NAMES:
            Group.objects.using(using).get_or_create(name=role_name)
    except (OperationalError, ProgrammingError):
        return
