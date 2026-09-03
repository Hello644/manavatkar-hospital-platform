import re

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import DoctorProfile
from apps.opd import booking

MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


class AppointmentBookingForm(forms.Form):
    """The public booking form. Deliberately asks for the minimum the DPDP Act
    allows us to collect for this purpose: who to expect, and how to reach them.
    Age, sex, address and history are captured at reception, on consent."""

    full_name = forms.CharField(
        label=_("Patient name"), max_length=120,
        widget=forms.TextInput(attrs={"autocomplete": "name", "placeholder": _("Full name")}),
    )
    mobile = forms.CharField(
        label=_("Mobile number"), max_length=15,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "autocomplete": "tel",
            "placeholder": "9876543210",
        }),
    )
    doctor = forms.ModelChoiceField(
        label=_("Doctor"),
        queryset=DoctorProfile.objects.none(),
        empty_label=_("Select a doctor"),
    )
    date = forms.DateField(
        label=_("Date"),
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    slot_time = forms.ChoiceField(label=_("Time"), choices=[])
    reason = forms.CharField(
        label=_("Reason for visit (optional)"), max_length=120, required=False,
        widget=forms.TextInput(attrs={"placeholder": _("e.g. fever, follow-up")}),
    )
    # Honeypot: hidden from humans by CSS, irresistible to naive form bots.
    website = forms.CharField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, slot_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = DoctorProfile.objects.filter(
            accepts_online_booking=True, show_on_website=True
        ).order_by("display_name")
        # Slots depend on the doctor+date the visitor picked, so the choices are
        # injected by the view after it has resolved them. Validation still runs
        # against this list, and booking re-checks under a row lock anyway.
        self.fields["slot_time"].choices = [(s, s) for s in (slot_choices or [])]

    def clean_mobile(self):
        digits = booking.normalise_mobile(self.cleaned_data["mobile"])
        if not MOBILE_RE.match(digits):
            raise forms.ValidationError(_("Enter a valid 10-digit Indian mobile number."))
        return digits

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())
        if len(name) < 2:
            raise forms.ValidationError(_("Please enter the patient's name."))
        return name

    def is_spam(self):
        return bool(self.data.get("website"))
