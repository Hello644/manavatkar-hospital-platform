"""OPD access-control helpers.

The canonical role sets and ``role_required`` gate live in
``apps.accounts.permissions``; re-exported here so existing ``opd`` imports keep
working.
"""

from apps.accounts.permissions import (  # noqa: F401
    CLINICAL_READ_ROLES,
    DOCTOR_ROLES,
    FRONT_DESK_ROLES,
    NURSE_ROLES,
    PATIENT_MANAGE_ROLES,
    REPORT_ROLES,
    role_required,
    user_in_roles,
)
