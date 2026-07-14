from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient

from . import services
from .forms import AppointmentForm, QuickUnknownPatientForm, VitalsForm, WalkInVisitForm
from .models import Appointment, Receipt, Visit

User = get_user_model()


def make_user(username, role=None, **kwargs):
    user = User.objects.create_user(username=username, password="pass12345", **kwargs)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def make_doctor(username="drrajesh", display_name="Dr. Rajesh Manavatkar", room="A"):
    user = make_user(username, role="doctor")
    return DoctorProfile.objects.create(
        user=user,
        display_name=display_name,
        registration_number="80166",
        room_label=room,
        consult_fee=Decimal("200"),
    )


def make_patient(name="Sita Patil", mobile="9876543210", age=30):
    return Patient.objects.create(
        full_name=name,
        mobile=mobile,
        sex=Patient.Sex.FEMALE,
        age_years_at_registration=age,
        dob=timezone.localdate() - timedelta(days=age * 365),
        privacy_notice_accepted=True,
    )


class TokenAndReceiptTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.other = make_doctor("drmadhu", "Dr. Madhu Manavatkar", room="B")
        self.patient = make_patient()
        self.receptionist = make_user("recept", role="receptionist")

    def test_tokens_increment_per_doctor_per_day(self):
        today = timezone.localdate()
        number1, label1 = services.next_token(self.doctor, today)
        number2, label2 = services.next_token(self.doctor, today)
        other_number, other_label = services.next_token(self.other, today)
        self.assertEqual((number1, number2), (1, 2))
        self.assertEqual(label1, "A-001")
        self.assertEqual(label2, "A-002")
        self.assertEqual(other_number, 1)
        self.assertEqual(other_label, "B-001")

    def test_receipt_number_format_and_sequence(self):
        first = services.next_receipt_no()
        second = services.next_receipt_no()
        year = timezone.localdate().year % 100
        self.assertEqual(first, f"RCT-{year:02d}-000001")
        self.assertEqual(second, f"RCT-{year:02d}-000002")

    def test_create_visit_with_fee_creates_receipt(self):
        visit, receipt = services.create_visit(
            patient=self.patient,
            doctor=self.doctor,
            user=self.receptionist,
            fee_amount=Decimal("200"),
            payment_mode=Receipt.Mode.CASH,
        )
        self.assertIsNotNone(receipt)
        self.assertEqual(visit.paid_amount, Decimal("200"))
        self.assertEqual(visit.token_label, "A-001")

    def test_create_visit_free_has_no_receipt(self):
        visit, receipt = services.create_visit(
            patient=self.patient,
            doctor=self.doctor,
            user=self.receptionist,
            fee_amount=Decimal("0"),
            payment_mode="",
        )
        self.assertIsNone(receipt)
        self.assertEqual(visit.receipts.count(), 0)


class QueueTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.user = make_user("recept", role="receptionist")

    def visit_for(self, name, **kwargs):
        patient = make_patient(name=name, mobile="")
        patient.no_phone = True
        patient.save()
        visit, _receipt = services.create_visit(
            patient=patient, doctor=self.doctor, user=self.user, **kwargs
        )
        return visit

    def test_queue_order_emergency_appointment_walkin(self):
        walk_in = self.visit_for("Walk In")
        appointment = self.visit_for("Appt Patient", source=Visit.Source.APPOINTMENT)
        emergency = self.visit_for("Emergency Patient", is_emergency=True)
        queue = list(services.waiting_queue(self.doctor))
        self.assertEqual(
            [visit.pk for visit in queue], [emergency.pk, appointment.pk, walk_in.pk]
        )

    def test_call_next_moves_to_in_consult(self):
        visit = self.visit_for("Solo")
        called = services.call_next(self.doctor)
        self.assertEqual(called.pk, visit.pk)
        called.refresh_from_db()
        self.assertEqual(called.status, Visit.Status.IN_CONSULT)
        self.assertIsNotNone(called.called_at)
        self.assertIsNone(services.call_next(self.doctor))

    def test_skip_drops_behind_then_parks(self):
        first = self.visit_for("First")
        second = self.visit_for("Second")
        services.skip(first)
        queue = list(services.waiting_queue(self.doctor))
        self.assertEqual([visit.pk for visit in queue], [second.pk, first.pk])
        first.refresh_from_db()
        services.skip(first)
        first.refresh_from_db()
        self.assertEqual(first.status, Visit.Status.PARKED)

    def test_hold_resume_returns_to_front(self):
        held = self.visit_for("Held")
        self.visit_for("Waiting")
        services.start_consult(held)
        services.hold(held)
        services.resume(held)
        queue = list(services.waiting_queue(self.doctor))
        self.assertEqual(queue[0].pk, held.pk)

    def test_emergency_outranks_resumed_hold(self):
        resumed = self.visit_for("Resumed")
        services.start_consult(resumed)
        services.hold(resumed)
        services.resume(resumed)
        emergency = self.visit_for("Emergency", is_emergency=True)
        queue = list(services.waiting_queue(self.doctor))
        # Patient safety: a flagged emergency must beat a resumed routine hold.
        self.assertEqual(queue[0].pk, emergency.pk)

    def test_call_next_refuses_second_concurrent_consult(self):
        first = self.visit_for("First")
        self.visit_for("Second")
        called = services.call_next(self.doctor)
        self.assertEqual(called.pk, first.pk)
        # A second call while one is already in consult must return nothing.
        self.assertIsNone(services.call_next(self.doctor))

    def test_complete_requires_disposition(self):
        visit = self.visit_for("Complete Me")
        services.start_consult(visit)
        with self.assertRaises(ValidationError):
            services.complete(visit, disposition="")
        completed = services.complete(
            visit, disposition=Visit.Disposition.FOLLOW_UP, followup_days=7
        )
        self.assertEqual(completed.status, Visit.Status.COMPLETED)
        self.assertIsNotNone(completed.completed_at)

    def test_referred_requires_destination(self):
        visit = self.visit_for("Referred")
        services.start_consult(visit)
        with self.assertRaises(ValidationError):
            services.complete(visit, disposition=Visit.Disposition.REFERRED)


class MlcAndVitalsTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.user = make_user("recept", role="receptionist")

    def test_quick_unknown_patient_passes_validation(self):
        form = QuickUnknownPatientForm(
            data={"sex": "M", "approximate_age": 40, "identifying_note": "Blue shirt"}
        )
        self.assertTrue(form.is_valid())
        patient = form.build_patient(self.user)
        patient.full_clean()
        patient.save()
        self.assertTrue(patient.is_unknown)
        self.assertTrue(patient.privacy_notice_deferred)
        self.assertIn("UNKNOWN", patient.full_name)

    def test_unknown_patient_visit_is_forced_to_mlc(self):
        qform = QuickUnknownPatientForm(data={"sex": "M", "approximate_age": 40})
        self.assertTrue(qform.is_valid())
        patient = qform.build_patient(self.user)
        patient.full_clean()
        patient.save()
        # Desk unchecks MLC and gives no context -> MLC is re-forced and the
        # medico-legal context becomes mandatory.
        form = WalkInVisitForm(
            data={"doctor": self.doctor.pk, "payment_mode": "free", "is_mlc": ""},
            patient=patient,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("mlc_brought_by", form.errors)
        form = WalkInVisitForm(
            data={
                "doctor": self.doctor.pk,
                "payment_mode": "free",
                "is_mlc": "",
                "mlc_police_station": "Bhusawal City PS",
            },
            patient=patient,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["is_mlc"])

    def test_mlc_visit_requires_context(self):
        patient = make_patient()
        with self.assertRaises(ValidationError):
            services.create_visit(
                patient=patient, doctor=self.doctor, user=self.user, is_mlc=True
            )
        visit, _receipt = services.create_visit(
            patient=patient,
            doctor=self.doctor,
            user=self.user,
            is_mlc=True,
            mlc_police_station="Bhusawal City PS",
        )
        self.assertTrue(visit.is_mlc)

    def test_vitals_weight_mandatory_under_12(self):
        child = Patient.objects.create(
            full_name="Chhotu Patil",
            mobile="9876500000",
            sex=Patient.Sex.MALE,
            dob=timezone.localdate() - timedelta(days=6 * 365),
            guardian_name="Ramesh Patil",
            guardian_relationship="Father",
            privacy_notice_accepted=True,
        )
        visit, _receipt = services.create_visit(
            patient=child, doctor=self.doctor, user=self.user
        )
        form = VitalsForm(data={"pulse": 90}, visit=visit)
        self.assertFalse(form.is_valid())
        self.assertIn("weight_kg", form.errors)
        form = VitalsForm(data={"weight_kg": "18.5", "pulse": 90}, visit=visit)
        self.assertTrue(form.is_valid())

    def test_vitals_bp_must_be_pair(self):
        patient = make_patient()
        visit, _receipt = services.create_visit(
            patient=patient, doctor=self.doctor, user=self.user
        )
        form = VitalsForm(data={"bp_systolic": 120}, visit=visit)
        self.assertFalse(form.is_valid())
        form = VitalsForm(data={"bp_systolic": 120, "bp_diastolic": 80}, visit=visit)
        self.assertTrue(form.is_valid())


class ViewPermissionTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.receptionist = make_user("recept", role="receptionist")
        self.nurse = make_user("nurse1", role="nurse")

    def test_display_is_public_and_has_no_names(self):
        services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )
        page = self.client.get(reverse("opd:display"))
        self.assertEqual(page.status_code, 200)
        data = self.client.get(reverse("opd:display_data"))
        self.assertEqual(data.status_code, 200)
        self.assertNotIn(self.patient.full_name, data.content.decode())
        payload = data.json()
        self.assertEqual(payload["doctors"][0]["next"], ["A-001"])

    def test_queue_board_requires_login(self):
        response = self.client.get(reverse("opd:queue_board"))
        self.assertEqual(response.status_code, 302)

    def test_clinical_chart_read_is_role_gated(self):
        visit, _receipt = services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )
        detail_url = reverse("opd:visit_detail", args=[visit.pk])
        slip_url = reverse("opd:slip", args=[visit.pk])

        for role in ("pharmacist", "staff"):
            user = make_user(f"{role}_user", role=role)
            self.client.force_login(user)
            self.assertEqual(self.client.get(detail_url).status_code, 403)
            self.assertEqual(self.client.get(slip_url).status_code, 403)

        # Clinical/desk roles retain access.
        self.client.force_login(self.nurse)
        self.assertEqual(self.client.get(detail_url).status_code, 200)
        self.client.force_login(self.receptionist)
        self.assertEqual(self.client.get(slip_url).status_code, 200)

    def test_collections_forbidden_for_nurse(self):
        self.client.force_login(self.nurse)
        response = self.client.get(reverse("opd:collection_register"))
        self.assertEqual(response.status_code, 403)
        self.client.force_login(self.receptionist)
        response = self.client.get(reverse("opd:collection_register"))
        self.assertEqual(response.status_code, 200)

    def test_new_visit_flow_creates_visit_and_receipt(self):
        self.client.force_login(self.receptionist)
        response = self.client.post(
            f"{reverse('opd:new_visit')}?patient={self.patient.pk}",
            {
                "patient": str(self.patient.pk),
                "doctor": self.doctor.pk,
                "fee_amount": "200",
                "payment_mode": "cash",
            },
        )
        visit = Visit.objects.get()
        self.assertRedirects(response, reverse("opd:slip", args=[visit.pk]))
        self.assertEqual(visit.receipts.count(), 1)

    def test_appointment_check_in_links_visit(self):
        appointment = Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=timezone.localdate(),
            slot_time="10:00",
            created_by=self.receptionist,
        )
        self.client.force_login(self.receptionist)
        self.client.post(
            f"{reverse('opd:new_visit')}?patient={self.patient.pk}&appointment={appointment.pk}",
            {
                "patient": str(self.patient.pk),
                "appointment": str(appointment.pk),
                "payment_mode": "free",
            },
        )
        appointment.refresh_from_db()
        self.assertEqual(appointment.status, Appointment.Status.CHECKED_IN)
        self.assertIsNotNone(appointment.visit)
        self.assertEqual(appointment.visit.source, Visit.Source.APPOINTMENT)

    def test_refund_marks_receipt(self):
        visit, receipt = services.create_visit(
            patient=self.patient,
            doctor=self.doctor,
            user=self.receptionist,
            fee_amount=Decimal("200"),
            payment_mode=Receipt.Mode.CASH,
        )
        self.client.force_login(self.receptionist)
        self.client.post(
            reverse("opd:receipt_refund", args=[receipt.pk]),
            {"refund_reason": "Patient left before consult"},
        )
        receipt.refresh_from_db()
        self.assertTrue(receipt.is_refunded)
        self.assertEqual(visit.paid_amount, Decimal("0"))


class FollowupAndRedirectTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.other = make_doctor("drmadhu", "Dr. Madhu", room="B")
        self.user = make_user("recept", role="receptionist")

    def _visit(self, name):
        patient = make_patient(name=name, mobile="")
        patient.no_phone = True
        patient.save()
        visit, _receipt = services.create_visit(
            patient=patient, doctor=self.doctor, user=self.user
        )
        return visit

    def test_complete_followup_records_date_and_call_list(self):
        visit = self._visit("Follow Up")
        services.start_consult(visit)
        services.complete(
            visit, disposition=Visit.Disposition.FOLLOW_UP, followup_days=7
        )
        visit.refresh_from_db()
        self.assertEqual(visit.followup_date, visit.visit_date + timedelta(days=7))
        due = list(services.followups_due(visit.followup_date, visit.followup_date))
        self.assertIn(visit, due)

        home = self._visit("Home")
        services.start_consult(home)
        services.complete(home, disposition=Visit.Disposition.HOME)
        home.refresh_from_db()
        self.assertIsNone(home.followup_date)

    def test_redirect_queue_moves_only_waiting_with_new_tokens(self):
        first = self._visit("One")
        second = self._visit("Two")
        services.call_next(self.doctor)  # 'first' goes into consult, must not move
        moved = services.redirect_queue(self.doctor, self.other)
        self.assertEqual([m.pk for m in moved], [second.pk])
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.doctor_id, self.other.pk)
        self.assertEqual(second.token_label, "B-001")
        self.assertEqual(first.doctor_id, self.doctor.pk)

    def test_followup_list_view_renders(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("opd:followup_list"))
        self.assertEqual(response.status_code, 200)

    def test_queue_redirect_view_moves_via_post(self):
        self._visit("Waiting")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("opd:queue_redirect"),
            {"from_doctor": self.doctor.pk, "to_doctor": self.other.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Visit.objects.filter(doctor=self.other, visit_date=timezone.localdate()).count(),
            1,
        )


class ConsultationNoteTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.receptionist = make_user("recept", role="receptionist")
        self.visit, _receipt = services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )

    def test_doctor_saves_note(self):
        self.client.force_login(self.doctor.user)
        response = self.client.post(
            reverse("opd:consult_note", args=[self.visit.pk]),
            {"chief_complaint": "Fever 3 days", "diagnosis": "Viral fever", "plan": "Rest, fluids"},
        )
        self.assertRedirects(response, reverse("opd:visit_detail", args=[self.visit.pk]))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.note.diagnosis, "Viral fever")
        self.assertEqual(self.visit.note.recorded_by, self.doctor.user)

    def test_other_doctor_cannot_edit_note(self):
        other = make_doctor("drother", "Dr. Other", room="C")
        self.client.force_login(other.user)
        response = self.client.post(
            reverse("opd:consult_note", args=[self.visit.pk]),
            {"diagnosis": "x"},
        )
        self.assertEqual(response.status_code, 403)

    def test_receptionist_cannot_edit_note(self):
        self.client.force_login(self.receptionist)
        response = self.client.get(reverse("opd:consult_note", args=[self.visit.pk]))
        self.assertEqual(response.status_code, 403)


class ThermalTokenTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.receptionist = make_user("recept", role="receptionist")

    def test_build_token_slip_is_valid_escpos(self):
        from apps.core.models import HospitalProfile

        from .escpos import FULL_CUT, INIT, build_token_slip

        visit, _receipt = services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )
        payload = build_token_slip(visit, HospitalProfile.get_solo())
        self.assertIsInstance(payload, bytes)
        self.assertTrue(payload.startswith(INIT))
        self.assertTrue(payload.endswith(FULL_CUT))
        self.assertIn(visit.token_label.encode("ascii"), payload)

    def test_mlc_token_carries_marker(self):
        from apps.core.models import HospitalProfile

        from .escpos import build_token_slip

        visit, _receipt = services.create_visit(
            patient=self.patient,
            doctor=self.doctor,
            user=self.receptionist,
            is_mlc=True,
            mlc_police_station="Bhusawal City PS",
        )
        payload = build_token_slip(visit, HospitalProfile.get_solo())
        self.assertIn(b"MEDICO-LEGAL", payload)

    def test_thermal_endpoint_returns_bytes_when_no_printer(self):
        visit, _receipt = services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )
        self.client.force_login(self.receptionist)
        response = self.client.get(reverse("opd:slip_escpos", args=[visit.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/octet-stream")
        self.assertTrue(response.content.startswith(b"\x1b@"))


class DoctorQueueViewTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.receptionist = make_user("recept", role="receptionist")
        self.patient = make_patient()
        self.visit, _receipt = services.create_visit(
            patient=self.patient, doctor=self.doctor, user=self.receptionist
        )

    def test_call_next_via_view(self):
        self.client.force_login(self.doctor.user)
        response = self.client.post(reverse("opd:queue_call_next"))
        self.assertRedirects(
            response, reverse("opd:visit_detail", args=[self.visit.pk])
        )
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.IN_CONSULT)

    def test_other_doctor_cannot_act_on_visit(self):
        other = make_doctor("drother", "Dr. Other", room="C")
        self.client.force_login(other.user)
        response = self.client.post(
            reverse("opd:queue_action", args=[self.visit.pk, "skip"])
        )
        self.assertEqual(response.status_code, 403)

    def test_complete_and_next(self):
        second_patient = make_patient(name="Next Patient", mobile="9876511111")
        second_visit, _receipt = services.create_visit(
            patient=second_patient, doctor=self.doctor, user=self.receptionist
        )
        services.start_consult(self.visit)
        self.client.force_login(self.doctor.user)
        response = self.client.post(
            reverse("opd:visit_complete", args=[self.visit.pk]),
            {"disposition": "home", "complete_and_next": "1"},
        )
        self.assertRedirects(
            response, reverse("opd:visit_detail", args=[second_visit.pk])
        )
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)

    def test_recall_rejected_for_completed_visit(self):
        services.start_consult(self.visit)
        services.complete(self.visit, disposition=Visit.Disposition.HOME)
        self.visit.refresh_from_db()
        called_before = self.visit.called_at
        self.client.force_login(self.doctor.user)
        self.client.post(reverse("opd:queue_action", args=[self.visit.pk, "recall"]))
        self.visit.refresh_from_db()
        # recall must not touch a completed visit's call timestamp.
        self.assertEqual(self.visit.called_at, called_before)
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)


class AppointmentFormTests(TestCase):
    def setUp(self):
        self.doctor = make_doctor()
        self.patient = make_patient()
        self.receptionist = make_user("recept", role="receptionist")
        self.tomorrow = timezone.localdate() + timedelta(days=1)

    def test_slot_clash_rejected(self):
        Appointment.objects.create(
            patient=self.patient,
            doctor=self.doctor,
            date=self.tomorrow,
            slot_time="10:00",
            created_by=self.receptionist,
        )
        form = AppointmentForm(
            data={
                "doctor": self.doctor.pk,
                "date": self.tomorrow.isoformat(),
                "slot_time": "10:00",
                "duration_minutes": 10,
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("slot_time", form.errors)

    def test_past_date_rejected(self):
        form = AppointmentForm(
            data={
                "doctor": self.doctor.pk,
                "date": (timezone.localdate() - timedelta(days=1)).isoformat(),
                "slot_time": "10:00",
                "duration_minutes": 10,
                "notes": "",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("date", form.errors)
