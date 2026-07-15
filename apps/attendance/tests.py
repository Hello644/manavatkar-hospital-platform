import json
import tempfile
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    LeaveRequest,
    LeaveType,
    PunchEvent,
    RegularizationRequest,
    Shift,
    ShiftInstance,
    StaffProfile,
)

User = get_user_model()


def make_staff(username="sister", role="nurse", employee_code="1001", pin="123456"):
    user = User.objects.create_user(username=username, password="x", employee_code=employee_code)
    user.groups.add(Group.objects.get(name=role))
    if pin:
        user.set_pin(pin)
        user.save()
    return StaffProfile.objects.create(user=user, designation="Nurse")


def aware(d, t):
    return timezone.make_aware(datetime.combine(d, t), timezone.get_current_timezone())


class ShiftInstanceTests(TestCase):
    def test_night_shift_crosses_midnight(self):
        night = Shift.objects.create(name="Night", start_time=time(22, 0), end_time=time(6, 0))
        self.assertTrue(night.crosses_midnight)
        staff = make_staff()
        today = timezone.localdate()
        inst = services.make_shift_instance(staff, night, today)
        self.assertEqual(inst.window_start.date(), today)
        # OUT window lands on the next calendar day.
        self.assertEqual(inst.window_end.date(), today + timedelta(days=1))


class DerivationTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.shift = Shift.objects.create(
            name="Morning", start_time=time(8, 0), end_time=time(16, 0), grace_minutes=10
        )
        self.today = timezone.localdate()
        self.inst = services.make_shift_instance(self.staff, self.shift, self.today)

    def test_present_and_in_out(self):
        services.record_punch(staff=self.staff, event_time=aware(self.today, time(8, 5)))
        services.record_punch(staff=self.staff, event_time=aware(self.today, time(16, 2)))
        record = services.derive_attendance(self.inst)
        self.assertEqual(record.status, record.Status.PRESENT)
        self.assertEqual(timezone.localtime(record.first_in).hour, 8)
        self.assertEqual(timezone.localtime(record.last_out).hour, 16)
        self.assertGreater(record.worked_minutes, 400)

    def test_late_detection(self):
        services.record_punch(staff=self.staff, event_time=aware(self.today, time(8, 25)))
        record = services.derive_attendance(self.inst)
        self.assertEqual(record.status, record.Status.LATE)

    def test_absent_when_no_punch(self):
        record = services.derive_attendance(self.inst)
        self.assertEqual(record.status, record.Status.ABSENT)

    def test_who_is_in_is_odd_punch_toggle(self):
        services.record_punch(staff=self.staff, event_time=aware(self.today, time(9, 0)))
        self.assertEqual(len(services.who_is_in()), 1)  # 1 punch = in
        services.record_punch(staff=self.staff, event_time=aware(self.today, time(13, 0)))
        self.assertEqual(len(services.who_is_in()), 0)  # 2 punches = out


class CloseMissingTests(TestCase):
    def test_missing_punch_opens_regularization(self):
        staff = make_staff()
        shift = Shift.objects.create(name="Early", start_time=time(6, 0), end_time=time(7, 0))
        now = timezone.now()
        inst = ShiftInstance.objects.create(
            staff=staff, shift=shift, date=timezone.localdate(),
            window_start=now - timedelta(hours=3), window_end=now - timedelta(hours=2),
        )
        opened = services.close_missing_punches()
        self.assertEqual(opened, 1)
        inst.refresh_from_db()
        self.assertEqual(inst.status, ShiftInstance.Status.ABSENT)
        self.assertEqual(RegularizationRequest.objects.filter(status="open").count(), 1)


@override_settings(KIOSK_DEVICE_TOKEN="test-token")
class KioskPunchTests(TestCase):
    def setUp(self):
        self.staff = make_staff(employee_code="1001", pin="123456")

    def _post(self, body, token="test-token"):
        return self.client.post(
            reverse("attendance:punch"),
            data=json.dumps(body),
            content_type="application/json",
            HTTP_X_KIOSK_TOKEN=token,
        )

    def test_pin_punch_records_event(self):
        resp = self._post({"employee_code": "1001", "pin": "123456"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")
        self.assertEqual(PunchEvent.objects.filter(source="pin").count(), 1)

    def test_wrong_token_rejected(self):
        resp = self._post({"employee_code": "1001", "pin": "123456"}, token="bad")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(PunchEvent.objects.count(), 0)

    def test_wrong_pin_no_punch(self):
        resp = self._post({"employee_code": "1001", "pin": "000000"})
        self.assertEqual(resp.json()["status"], "error")
        self.assertEqual(PunchEvent.objects.count(), 0)


class DashboardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="boss", password="x", is_superuser=True, is_staff=True)
        self.staff = make_staff()

    def test_board_requires_role(self):
        nurse_user = self.staff.user
        self.client.force_login(nurse_user)
        self.assertEqual(self.client.get(reverse("attendance:board")).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("attendance:board")).status_code, 200)

    def test_payroll_export_xlsx(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("attendance:payroll_export"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("spreadsheetml", resp["Content-Type"])

    def test_leave_approval_marks_instances(self):
        shift = Shift.objects.create(name="Morning", start_time=time(8, 0), end_time=time(16, 0))
        today = timezone.localdate()
        inst = services.make_shift_instance(self.staff, shift, today)
        ltype = LeaveType.objects.create(name="Casual")
        leave = LeaveRequest.objects.create(
            staff=self.staff, leave_type=ltype, from_date=today, to_date=today, reason="x"
        )
        self.client.force_login(self.admin)
        self.client.post(reverse("attendance:leave_decide", args=[leave.pk]), {"decision": "approve"})
        inst.refresh_from_db()
        self.assertEqual(inst.status, ShiftInstance.Status.LEAVE)
