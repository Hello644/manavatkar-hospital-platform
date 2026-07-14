import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models

from apps.prescriptions.models import Drug


class StockItem(models.Model):
    """On-hand stock for a formulary drug (or a free-named item). The on-hand
    quantity is a running total maintained by StockTransaction ledger entries."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    drug = models.OneToOneField(
        Drug, null=True, blank=True, on_delete=models.SET_NULL, related_name="stock"
    )
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=24, blank=True, default="unit")
    quantity_on_hand = models.IntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.quantity_on_hand} {self.unit})"

    @property
    def is_low(self):
        return self.quantity_on_hand <= self.reorder_level


class StockTransaction(models.Model):
    class Reason(models.TextChoices):
        RECEIVE = "receive", "Stock received"
        DISPENSE = "dispense", "Dispensed"
        ADJUST = "adjust", "Adjustment"
        RETURN = "return", "Return"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    item = models.ForeignKey(StockItem, on_delete=models.CASCADE, related_name="transactions")
    change = models.IntegerField(help_text="Positive to add stock, negative to remove")
    reason = models.CharField(max_length=12, choices=Reason.choices)
    reference = models.CharField(max_length=120, blank=True, help_text="e.g. Rx id, invoice no.")
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="stock_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.item.name} {self.change:+d} ({self.reason})"


auditlog.register(StockItem)
auditlog.register(StockTransaction)
