from django import forms
from django.conf import settings

from .models import Patient
from .services import approximate_dob_from_age, normalize_mobile, normalize_name


class PatientForm(forms.ModelForm):
    age_years = forms.IntegerField(
        required=False,
        min_value=0,
        max_value=120,
        help_text="Use age when exact date of birth is not known.",
    )

    class Meta:
        model = Patient
        fields = [
            "full_name",
            "mobile",
            "no_phone",
            "age_years",
            "age_years_at_registration",
            "dob",
            "sex",
            "address_line",
            "area_village",
            "city",
            "district",
            "pincode",
            "old_file_number",
            "guardian_name",
            "guardian_relationship",
            "preferred_language",
            "abha_number",
            "abha_address",
            "blood_group",
            "email",
            "aadhaar_last4",
            "emergency_contact_name",
            "emergency_contact_phone",
            "referral_source",
            "privacy_notice_accepted",
        ]
        widgets = {
            "dob": forms.DateInput(attrs={"type": "date"}),
            "age_years_at_registration": forms.HiddenInput(),
            "address_line": forms.TextInput(attrs={"autocomplete": "street-address"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if self.instance and self.instance.pk and self.instance.age_years_at_registration:
            self.fields["age_years"].initial = self.instance.age_years_at_registration
        self.fields["privacy_notice_accepted"].label = (
            "Patient privacy notice accepted"
        )

    def clean_mobile(self):
        mobile = normalize_mobile(self.cleaned_data.get("mobile"))
        if mobile and len(mobile) != 10:
            raise forms.ValidationError("Enter a 10-digit Indian mobile number.")
        return mobile

    def clean_aadhaar_last4(self):
        value = self.cleaned_data.get("aadhaar_last4", "")
        if value and (not value.isdigit() or len(value) != 4):
            raise forms.ValidationError("Store only the last 4 Aadhaar digits.")
        return value

    def clean(self):
        cleaned = super().clean()
        mobile = cleaned.get("mobile")
        no_phone = cleaned.get("no_phone")
        dob = cleaned.get("dob")
        age_years = cleaned.get("age_years")

        if not mobile and not no_phone:
            self.add_error("mobile", "Mobile is required unless no-phone is checked.")
        if mobile and no_phone:
            cleaned["no_phone"] = False
        if not dob and age_years is None:
            self.add_error("age_years", "Enter age or date of birth.")
        if age_years is not None:
            cleaned["age_years_at_registration"] = age_years

        effective_age = age_years
        if dob:
            # A Patient's UUID pk is populated by its field default even before
            # save, so `self.instance.pk` is not a reliable "is this saved?"
            # flag — use created_at (None until first save). Existing patients
            # are aged as of their registration date; new ones as of today.
            created_at = self.instance.created_at
            reference = created_at.date() if created_at else None
            effective_age = Patient(dob=dob, sex=cleaned.get("sex") or "O").get_age_years(
                reference
            )
        if effective_age is not None and effective_age < 18:
            if not cleaned.get("guardian_name"):
                self.add_error("guardian_name", "Guardian name is required for minors.")
            if not cleaned.get("guardian_relationship"):
                self.add_error(
                    "guardian_relationship",
                    "Guardian relationship is required for minors.",
                )
        if not cleaned.get("privacy_notice_accepted"):
            self.add_error(
                "privacy_notice_accepted",
                "Privacy notice acceptance is required.",
            )
        return cleaned

    def save(self, commit=True):
        patient = super().save(commit=False)
        age_years = self.cleaned_data.get("age_years")
        if not patient.dob and age_years is not None:
            patient.dob = approximate_dob_from_age(age_years)
            patient.dob_estimated = True
            patient.age_years_at_registration = age_years
        elif patient.dob:
            patient.dob_estimated = False
            if age_years is not None:
                patient.age_years_at_registration = age_years
        patient.name_normalized = normalize_name(patient.full_name)
        if patient.privacy_notice_accepted and not patient.privacy_notice_version:
            patient.privacy_notice_version = settings.HOSPITAL_PRIVACY_NOTICE_VERSION
        if self.user:
            if not patient.pk:
                patient.created_by = self.user
            patient.updated_by = self.user
        if commit:
            patient.full_clean()
            patient.save()
        return patient
