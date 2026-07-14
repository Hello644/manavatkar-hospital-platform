from django.db import transaction

from .models import StockItem, StockTransaction


@transaction.atomic
def apply_transaction(*, item, change, reason, user=None, reference="", note=""):
    """Record a ledger entry and update the running on-hand quantity atomically."""
    locked = StockItem.objects.select_for_update().get(pk=item.pk)
    locked.quantity_on_hand = locked.quantity_on_hand + change
    locked.save(update_fields=["quantity_on_hand", "updated_at"])
    return StockTransaction.objects.create(
        item=locked, change=change, reason=reason, reference=reference,
        note=note, created_by=user,
    )


def stock_for_drug(drug):
    if drug is None:
        return None
    return StockItem.objects.filter(drug=drug, is_active=True).first()


def ensure_stock_item(drug):
    """Create a stock row for a formulary drug on first receive."""
    item, _created = StockItem.objects.get_or_create(
        drug=drug, defaults={"name": drug.label, "unit": drug.form or "unit"}
    )
    return item
