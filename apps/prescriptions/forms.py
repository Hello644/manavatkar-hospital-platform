from django import forms


class PrescriptionHeaderForm(forms.Form):
    diagnosis = forms.CharField(required=False, max_length=240)
    advice = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2})
    )
    followup_days = forms.IntegerField(required=False, min_value=1, max_value=365)
    allergy_override_reason = forms.CharField(required=False, max_length=240)
