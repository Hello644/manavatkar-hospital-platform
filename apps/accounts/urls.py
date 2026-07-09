from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("pin-switch/", views.pin_switch, name="pin_switch"),
    path("set-pin/", views.set_pin, name="set_pin"),
]

