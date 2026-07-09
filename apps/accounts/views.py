from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.shortcuts import redirect, render

from .forms import PinSwitchForm, SetPinForm


User = get_user_model()


@login_required
def pin_switch(request):
    users = User.objects.filter(is_active=True, pin_hash__gt="").order_by(
        "first_name", "last_name", "username"
    )
    form = PinSwitchForm(request.POST or None)
    selected_user_id = request.POST.get("user_id") if request.method == "POST" else None

    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user_id"]
        user.reset_pin_failures()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, f"Switched to {user.get_full_name() or user.username}.")
        return redirect("dashboard")

    return render(
        request,
        "accounts/pin_switch.html",
        {"form": form, "users": users, "selected_user_id": selected_user_id},
    )


@login_required
def set_pin(request):
    form = SetPinForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        request.user.set_pin(form.cleaned_data["pin"])
        request.user.save(update_fields=["pin_hash", "pin_set_at", "must_change_pin"])
        messages.success(request, "PIN updated.")
        return redirect("dashboard")
    return render(request, "accounts/set_pin.html", {"form": form})

