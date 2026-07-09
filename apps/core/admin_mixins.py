"""Admin mixins enforcing the PLAN.md / DPDP retention rule that clinical and
medico-legal records are immutable: soft-delete only, never hard-deleted."""


class NoHardDeleteAdminMixin:
    """Disable the Django-admin delete action and per-object delete button.

    Clinical/MLC records (patients, visits, vitals, receipts, appointments) must
    never be destroyed from the UI — litigation/MLC retention is 5–10+ years.
    Corrections happen via soft-delete/versioning, not deletion. True deletion,
    if ever legally required, is a deliberate DBA action outside the app.
    """

    def has_delete_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions
