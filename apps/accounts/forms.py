from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError


User = get_user_model()


class PinSwitchForm(forms.Form):
    user_id = forms.ModelChoiceField(
        queryset=User.objects.none(),
        widget=forms.HiddenInput,
        error_messages={"invalid_choice": "Choose an active user."},
    )
    pin = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user_id"].queryset = User.objects.filter(
            is_active=True, pin_hash__gt=""
        ).order_by("first_name", "last_name", "username")

    def clean(self):
        cleaned = super().clean()
        user = cleaned.get("user_id")
        pin = cleaned.get("pin")
        if user and pin and not user.check_pin(pin):
            raise ValidationError("Incorrect PIN.")
        return cleaned


class SetPinForm(forms.Form):
    pin = forms.CharField(
        label="New PIN",
        max_length=6,
        min_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )
    confirm_pin = forms.CharField(
        label="Confirm PIN",
        max_length=6,
        min_length=6,
        widget=forms.PasswordInput(attrs={"inputmode": "numeric", "autocomplete": "off"}),
    )

    def clean_pin(self):
        pin = self.cleaned_data["pin"]
        if not pin.isdigit():
            raise ValidationError("PIN must contain digits only.")
        return pin

    def clean(self):
        cleaned = super().clean()
        pin = cleaned.get("pin")
        confirm_pin = cleaned.get("confirm_pin")
        if pin and confirm_pin and pin != confirm_pin:
            raise ValidationError("PIN confirmation does not match.")
        return cleaned

