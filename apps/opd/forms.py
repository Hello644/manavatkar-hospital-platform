from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import DoctorProfile
from apps.patients.models import Patient

from .models import Appointment, Receipt, Visit, VitalsRecord


PAYMENT_CHOICES = [
    (Receipt.Mode.CASH, "Cash"),
    (Receipt.Mode.UPI, "UPI"),
    ("free", "No charge"),
]


def active_doctors():
    return DoctorProfile.objects.order_by("display_name")


class WalkInVisitForm(forms.Form):
    doctor = forms.ModelChoiceField(queryset=DoctorProfile.objects.none())
    is_emergency = forms.BooleanField(required=False, label="Emergency (jumps queue)")
    is_mlc = forms.BooleanField(required=False, label="Medico-legal case (MLC)")
    mlc_brought_by = forms.CharField(required=False, max_length=180, label="Brought by")
    mlc_police_station = forms.CharField(required=False, max_length=180, label="Police station")
    mlc_notes = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="MLC notes"
    )
    fee_amount = forms.DecimalField(
        required=False, min_value=Decimal("0"), max_digits=8, decimal_places=2
    )
    payment_mode = forms.ChoiceField(choices=PAYMENT_CHOICES, initial=Receipt.Mode.CASH)

    def __init__(self, *args, locked_doctor=None, patient=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.patient = patient
        self.fields["doctor"].queryset = active_doctors()
        if locked_doctor is not None:
            self.fields["doctor"].initial = locked_doctor
            self.fields["doctor"].disabled = True
        # An unknown/unconscious patient is always a medico-legal case; the flag
        # cannot be turned off at the desk.
        if patient is not None and patient.is_unknown:
            self.fields["is_mlc"].disabled = True
            self.fields["is_mlc"].initial = True
        self.fields["doctor"].widget.attrs["data-fees"] = ""

    def clean(self):
        cleaned = super().clean()
        doctor = cleaned.get("doctor")
        fee = cleaned.get("fee_amount")
        mode = cleaned.get("payment_mode")
        if fee is None and doctor is not None and mode != "free":
            cleaned["fee_amount"] = doctor.consult_fee
        if mode == "free":
            cleaned["fee_amount"] = Decimal("0")
        if self.patient is not None and self.patient.is_unknown:
            cleaned["is_mlc"] = True
        if cleaned.get("is_mlc") and not (
            cleaned.get("mlc_brought_by")
            or cleaned.get("mlc_police_station")
            or cleaned.get("mlc_notes")
        ):
            self.add_error(
                "mlc_brought_by",
                "Record who brought the patient or the police station for an MLC.",
            )
        return cleaned


class QuickUnknownPatientForm(forms.Form):
    sex = forms.ChoiceField(choices=Patient.Sex.choices)
    approximate_age = forms.IntegerField(min_value=0, max_value=120)
    identifying_note = forms.CharField(
        max_length=180,
        required=False,
        help_text="Clothing, marks, where found — anything that helps identify later.",
    )

    def build_patient(self, user):
        sex = self.cleaned_data["sex"]
        age = self.cleaned_data["approximate_age"]
        sex_label = dict(Patient.Sex.choices)[sex]
        patient = Patient(
            full_name=f"UNKNOWN {sex_label} ~{age}",
            sex=sex,
            age_years_at_registration=age,
            no_phone=True,
            is_unknown=True,
            privacy_notice_deferred=True,
            privacy_notice_deferred_reason="Unknown/unconscious patient — emergency registration",
            referral_source=self.cleaned_data.get("identifying_note", ""),
            created_by=user,
            updated_by=user,
        )
        from apps.patients.services import approximate_dob_from_age

        patient.dob = approximate_dob_from_age(age)
        patient.dob_estimated = True
        return patient


class AppointmentForm(forms.ModelForm):
    class Meta:
        model = Appointment
        fields = ["doctor", "date", "slot_time", "duration_minutes", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "slot_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = active_doctors()
        self.fields["duration_minutes"].initial = settings.OPD_DEFAULT_SLOT_MINUTES

    def clean_date(self):
        value = self.cleaned_data["date"]
        if value < timezone.localdate():
            raise forms.ValidationError("Appointment date cannot be in the past.")
        return value

    def clean(self):
        cleaned = super().clean()
        doctor = cleaned.get("doctor")
        date = cleaned.get("date")
        slot_time = cleaned.get("slot_time")
        if doctor and date and slot_time:
            clashes = Appointment.objects.filter(
                doctor=doctor,
                date=date,
                slot_time=slot_time,
                status__in=[Appointment.Status.BOOKED, Appointment.Status.CHECKED_IN],
            )
            if self.instance.pk:
                clashes = clashes.exclude(pk=self.instance.pk)
            if clashes.count() >= settings.OPD_SLOT_CAPACITY:
                self.add_error("slot_time", "This slot is already full for the doctor.")
        return cleaned


class VitalsForm(forms.ModelForm):
    class Meta:
        model = VitalsRecord
        fields = [
            "weight_kg",
            "height_cm",
            "bp_systolic",
            "bp_diastolic",
            "pulse",
            "spo2",
            "temp_f",
            "rbs",
            "pain_score",
            "lmp_date",
            "chief_complaint",
        ]
        widgets = {"lmp_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, visit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.visit = visit or getattr(self.instance, "visit", None)

    def clean(self):
        cleaned = super().clean()
        systolic = cleaned.get("bp_systolic")
        diastolic = cleaned.get("bp_diastolic")
        if (systolic is None) != (diastolic is None):
            self.add_error("bp_systolic", "Enter both systolic and diastolic BP.")
        if systolic and diastolic and systolic <= diastolic:
            self.add_error("bp_systolic", "Systolic must be greater than diastolic.")
        if self.visit is not None:
            age = self.visit.patient.get_age_years()
            if age is not None and age < 12 and not cleaned.get("weight_kg"):
                self.add_error("weight_kg", "Weight is mandatory for children under 12.")
        return cleaned


class CompleteVisitForm(forms.Form):
    disposition = forms.ChoiceField(choices=Visit.Disposition.choices)
    disposition_note = forms.CharField(required=False, max_length=240)
    followup_days = forms.IntegerField(required=False, min_value=1, max_value=365)
    referred_to = forms.CharField(required=False, max_length=180)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("disposition") == Visit.Disposition.REFERRED and not cleaned.get(
            "referred_to"
        ):
            self.add_error("referred_to", "Enter where the patient was referred.")
        if cleaned.get("disposition") == Visit.Disposition.FOLLOW_UP and not cleaned.get(
            "followup_days"
        ):
            self.add_error("followup_days", "Enter the follow-up interval in days.")
        return cleaned


class RefundForm(forms.Form):
    refund_reason = forms.CharField(max_length=240)


class CancelDayForm(forms.Form):
    doctor = forms.ModelChoiceField(queryset=DoctorProfile.objects.none())
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(max_length=240)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = active_doctors()
