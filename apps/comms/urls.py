from django.urls import path

from . import views

app_name = "comms"

urlpatterns = [
    path("share/rx/<uuid:pk>/", views.share_prescription, name="share_prescription"),
    path("outbox/", views.outbox, name="outbox"),
]
