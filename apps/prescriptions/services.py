import re

from django.db import transaction
from django.db.models import Q

from .models import Drug, Prescription, PrescriptionItem


# Dosage shorthand -> doses per day.
FREQUENCY_PER_DAY = {
    "od": 1, "hs": 1, "stat": 1, "sos": 0, "prn": 0,
    "bd": 2, "bid": 2, "tds": 3, "tid": 3, "qid": 4, "qds": 4,
}


def doses_per_day(dosage):
    """Parse '1-0-1', 'BD', 'OD x' etc. into a per-day dose count (0 = PRN)."""
    if not dosage:
        return None
    text = dosage.strip().lower()
    slots = re.findall(r"\d+(?:\.\d+)?", text.split("x")[0])
    if "-" in text and slots:
        return sum(float(n) for n in slots)
    for token, per_day in FREQUENCY_PER_DAY.items():
        if re.search(rf"\b{token}\b", text):
            return per_day
    if slots:
        return float(slots[0])
    return None


def computed_quantity(dosage, duration_days):
    per_day = doses_per_day(dosage)
    if not per_day or not duration_days:
        return None
    qty = per_day * duration_days
    return int(qty) + (1 if qty != int(qty) else 0)


def allergy_conflicts(patient, item_specs):
    """Return a list of (substance, matched_text) where a prescribed ingredient
    collides with a recorded patient allergy. Ingredient-level hard-stop (PLAN §5)."""
    allergy_tokens = {
        a.substance.strip().lower(): a.substance
        for a in patient.allergies.all()
        if a.substance.strip()
    }
    if not allergy_tokens:
        return []
    conflicts = []
    for spec in item_specs:
        tokens = set()
        drug = spec.get("drug")
        if drug is not None:
            tokens.update(drug.ingredient_tokens())
        text = (spec.get("drug_text") or "").lower()
        for allergy_key, substance in allergy_tokens.items():
            hit = allergy_key in tokens or (allergy_key and allergy_key in text)
            if hit:
                conflicts.append((substance, spec.get("drug_text") or (drug.label if drug else "")))
    return conflicts


@transaction.atomic
def create_prescription(*, patient, doctor, user, visit=None, diagnosis="", advice="",
                        followup_days=None, item_specs, allergy_override_reason=""):
    """item_specs: list of dicts {drug, drug_text, dosage, duration_days, quantity, instructions}."""
    rx = Prescription.objects.create(
        patient=patient,
        doctor=doctor,
        visit=visit,
        diagnosis=diagnosis,
        advice=advice,
        followup_days=followup_days,
        allergy_override_reason=allergy_override_reason,
        created_by=user,
    )
    for order, spec in enumerate(item_specs):
        drug = spec.get("drug")
        dosage = spec.get("dosage", "")
        duration = spec.get("duration_days")
        qty = spec.get("quantity") or computed_quantity(dosage, duration)
        PrescriptionItem.objects.create(
            prescription=rx,
            drug=drug,
            drug_text=spec.get("drug_text") or (drug.label if drug else ""),
            dosage=dosage,
            duration_days=duration,
            quantity=qty,
            instructions=spec.get("instructions", ""),
            order=order,
        )
        if drug is not None:
            Drug.objects.filter(pk=drug.pk).update(usage_count=drug.usage_count + 1)
    return rx


def search_formulary(query, limit=12):
    query = (query or "").strip()
    if not query:
        return Drug.objects.none()
    matches = (
        Q(generic_name__icontains=query)
        | Q(brand_name__icontains=query)
        | Q(ingredients__icontains=query)
    )
    return (
        Drug.objects.filter(is_active=True)
        .filter(matches)
        .order_by("-usage_count", "generic_name")[:limit]
    )
