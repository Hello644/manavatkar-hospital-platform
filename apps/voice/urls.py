from django.urls import path

from . import views

app_name = "voice"

urlpatterns = [
    path("incoming/", views.incoming, name="incoming"),
    path("turn/", views.turn, name="turn"),
    path("status/", views.status_callback, name="status"),
    path("log/", views.call_log, name="call_log"),
]
