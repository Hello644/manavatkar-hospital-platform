from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.permissions import PHARMACY_ROLES, role_required
from apps.prescriptions.models import Drug, Prescription

from . import services
from .models import StockItem, StockTransaction


@role_required(*PHARMACY_ROLES)
def stock_list(request):
    items = StockItem.objects.filter(is_active=True).select_related("drug")
    return render(
        request,
        "pharmacy/stock_list.html",
        {
            "items": items,
            "low_items": [i for i in items if i.is_low],
            "unstocked_drugs": Drug.objects.filter(is_active=True, stock__isnull=True).order_by(
                "generic_name"
            ),
        },
    )


@role_required(*PHARMACY_ROLES)
def stock_add(request):
    if request.method == "POST":
        drug_id = request.POST.get("drug")
        name = request.POST.get("name", "").strip()
        if drug_id:
            drug = get_object_or_404(Drug, pk=drug_id)
            item = services.ensure_stock_item(drug)
        elif name:
            item = StockItem.objects.create(name=name, unit=request.POST.get("unit", "unit"))
        else:
            messages.warning(request, "Pick a drug or enter an item name.")
            return redirect("pharmacy:stock_list")
        qty = int(request.POST.get("quantity") or 0)
        item.reorder_level = int(request.POST.get("reorder_level") or item.reorder_level)
        item.save(update_fields=["reorder_level"])
        if qty:
            services.apply_transaction(
                item=item, change=qty, reason=StockTransaction.Reason.RECEIVE,
                user=request.user, note="Initial / received",
            )
        messages.success(request, f"Stock item {item.name} saved.")
    return redirect("pharmacy:stock_list")


@role_required(*PHARMACY_ROLES)
def stock_move(request, pk):
    item = get_object_or_404(StockItem, pk=pk)
    if request.method == "POST":
        try:
            change = int(request.POST.get("change") or 0)
        except ValueError:
            change = 0
        reason = request.POST.get("reason") or StockTransaction.Reason.ADJUST
        if change:
            services.apply_transaction(
                item=item, change=change, reason=reason, user=request.user,
                note=request.POST.get("note", "")[:200],
            )
            messages.success(request, f"{item.name}: {change:+d} recorded.")
    return redirect("pharmacy:stock_list")


@role_required(*PHARMACY_ROLES)
def dispense(request, rx_pk):
    rx = get_object_or_404(
        Prescription.objects.select_related("patient").prefetch_related("items__drug"), pk=rx_pk
    )
    lines = []
    for item in rx.items.all():
        lines.append({"item": item, "stock": services.stock_for_drug(item.drug)})

    if request.method == "POST":
        dispensed = 0
        for line in lines:
            stock = line["stock"]
            if stock is None:
                continue
            qty = int(request.POST.get(f"qty_{line['item'].pk}") or 0)
            if qty > 0:
                services.apply_transaction(
                    item=stock, change=-qty, reason=StockTransaction.Reason.DISPENSE,
                    user=request.user, reference=f"Rx {rx.short_id}",
                )
                dispensed += 1
        messages.success(request, f"Dispensed {dispensed} item(s) against Rx {rx.short_id}.")
        return redirect("prescriptions:detail", pk=rx.pk)

    return render(request, "pharmacy/dispense.html", {"rx": rx, "lines": lines})
