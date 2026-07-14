from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import LabOrder, LabOrderItem, LabTest


def search_tests(query, limit=12):
    query = (query or "").strip()
    if not query:
        return LabTest.objects.none()
    matches = Q(name__icontains=query) | Q(short_code__icontains=query)
    return LabTest.objects.filter(is_active=True).filter(matches).order_by(
        "-usage_count", "name"
    )[:limit]


def resolve_test(text):
    text = (text or "").strip()
    if not text:
        return None
    for test in LabTest.objects.filter(is_active=True):
        if text.lower() in (test.label.lower(), test.name.lower(), (test.short_code or "").lower()):
            return test
    return None


@transaction.atomic
def create_lab_order(*, patient, doctor, user, visit=None, indication="", test_specs):
    order = LabOrder.objects.create(
        patient=patient, doctor=doctor, visit=visit, indication=indication, created_by=user,
    )
    for position, spec in enumerate(test_specs):
        test = spec.get("test")
        LabOrderItem.objects.create(
            order=order,
            test=test,
            test_text=spec.get("test_text") or (test.label if test else ""),
            result_unit=(test.default_unit if test else ""),
            reference_range=(test.reference_range if test else ""),
            position=position,
        )
        if test is not None:
            LabTest.objects.filter(pk=test.pk).update(usage_count=test.usage_count + 1)
    return order


@transaction.atomic
def save_results(order, rows, *, mark_reported=False):
    """rows: list of dicts keyed by item id -> {result_value, result_unit,
    reference_range, flag}."""
    for item in order.items.all():
        data = rows.get(str(item.pk))
        if not data:
            continue
        item.result_value = data.get("result_value", item.result_value)
        item.result_unit = data.get("result_unit", item.result_unit)
        item.reference_range = data.get("reference_range", item.reference_range)
        item.flag = data.get("flag", item.flag)
        item.save(update_fields=["result_value", "result_unit", "reference_range", "flag"])
    if mark_reported:
        order.status = LabOrder.Status.REPORTED
        order.reported_at = timezone.now()
        order.save(update_fields=["status", "reported_at", "updated_at"])
    return order


def set_status(order, status):
    order.status = status
    if status == LabOrder.Status.REPORTED and not order.reported_at:
        order.reported_at = timezone.now()
        order.save(update_fields=["status", "reported_at", "updated_at"])
    else:
        order.save(update_fields=["status", "updated_at"])
    return order
