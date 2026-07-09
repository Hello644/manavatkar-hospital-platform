from datetime import date
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone


MOBILE_RE = re.compile(r"^\d{10}$")


def normalize_name(value):
    return " ".join((value or "").strip().lower().split())


def normalize_mobile(value):
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return digits


def luhn_check_digit(number):
    total = 0
    reverse_digits = [int(digit) for digit in reversed(number)]
    for index, digit in enumerate(reverse_digits):
        if index % 2 == 0:
            doubled = digit * 2
            total += doubled - 9 if doubled > 9 else doubled
        else:
            total += digit
    return str((10 - (total % 10)) % 10)


def luhn_is_valid(number):
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 2:
        return False
    return luhn_check_digit(digits[:-1]) == digits[-1]


def approximate_dob_from_age(age_years, today=None):
    today = today or timezone.localdate()
    return date(today.year - int(age_years), 7, 1)


@transaction.atomic
def generate_uhid():
    from .models import PatientSequence

    today = timezone.localdate()
    year = today.year % 100
    code = settings.HOSPITAL_UHID_CODE[:3].upper()
    sequence, _created = PatientSequence.objects.select_for_update().get_or_create(
        year=year, defaults={"last_value": 0}
    )
    sequence.last_value += 1
    sequence.save(update_fields=["last_value", "updated_at"])

    serial = f"{sequence.last_value:06d}"
    check_digit = luhn_check_digit(f"{year:02d}{serial}")
    return f"{code}-{year:02d}-{serial}-{check_digit}"


def find_possible_duplicates(patient, limit=8):
    from .models import Patient

    query = Patient.objects.filter(is_active=True)
    if patient.pk:
        query = query.exclude(pk=patient.pk)

    matches = Patient.objects.none()
    if patient.mobile:
        matches = matches | query.filter(mobile=patient.mobile)

    if patient.name_normalized:
        name_bits = [bit for bit in patient.name_normalized.split() if len(bit) >= 3]
        name_query = query
        for bit in name_bits[:3]:
            name_query = name_query.filter(name_normalized__icontains=bit)
        matches = matches | name_query

    return matches.distinct().order_by("-created_at")[:limit]

