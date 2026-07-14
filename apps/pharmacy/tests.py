from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient
from apps.prescriptions.models import Drug
from apps.prescriptions.services import create_prescription

from . import services
from .models import StockItem, StockTransaction

User = get_user_model()


class StockLedgerTests(TestCase):
    def setUp(self):
        self.item = StockItem.objects.create(name="Dolo 650", quantity_on_hand=0, reorder_level=20)

    def test_transactions_update_running_total(self):
        services.apply_transaction(item=self.item, change=100, reason=StockTransaction.Reason.RECEIVE)
        services.apply_transaction(item=self.item, change=-30, reason=StockTransaction.Reason.DISPENSE)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_on_hand, 70)
        self.assertEqual(self.item.transactions.count(), 2)

    def test_low_stock_flag(self):
        services.apply_transaction(item=self.item, change=15, reason=StockTransaction.Reason.RECEIVE)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_low)


class DispenseViewTests(TestCase):
    def setUp(self):
        duser = User.objects.create_user(username="drrajesh", password="x")
        duser.groups.add(Group.objects.get(name="doctor"))
        self.doctor = DoctorProfile.objects.create(
            user=duser, display_name="Dr. Rajesh", registration_number="80166",
            prescription_enabled=True, room_label="A", consult_fee=Decimal("200"),
        )
        self.patient = Patient.objects.create(
            full_name="Sita", mobile="9876543210", sex=Patient.Sex.FEMALE,
            age_years_at_registration=30, privacy_notice_accepted=True,
        )
        self.pharmacist = User.objects.create_user(username="pharma", password="x")
        self.pharmacist.groups.add(Group.objects.get(name="pharmacist"))
        self.drug = Drug.objects.create(
            generic_name="Paracetamol", brand_name="Dolo", strength="650 mg", form="tablet",
        )
        self.stock = services.ensure_stock_item(self.drug)
        services.apply_transaction(item=self.stock, change=100, reason=StockTransaction.Reason.RECEIVE)
        self.rx = create_prescription(
            patient=self.patient, doctor=self.doctor, user=duser,
            item_specs=[{"drug": self.drug, "drug_text": self.drug.label, "dosage": "1-0-1",
                         "duration_days": 5, "quantity": 10}],
        )

    def test_dispense_decrements_stock(self):
        item = self.rx.items.get()
        self.client.force_login(self.pharmacist)
        response = self.client.post(
            reverse("pharmacy:dispense", args=[self.rx.pk]),
            {f"qty_{item.pk}": "10"},
        )
        self.assertRedirects(response, reverse("prescriptions:detail", args=[self.rx.pk]))
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantity_on_hand, 90)

    def test_non_pharmacist_blocked_from_stock(self):
        recept = User.objects.create_user(username="recept", password="x")
        recept.groups.add(Group.objects.get(name="receptionist"))
        self.client.force_login(recept)
        self.assertEqual(self.client.get(reverse("pharmacy:stock_list")).status_code, 403)
