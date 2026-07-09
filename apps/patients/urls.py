from django.urls import path

from . import views

app_name = "patients"

urlpatterns = [
    path("", views.patient_list, name="list"),
    path("new/", views.patient_create, name="create"),
    path("<uuid:pk>/", views.patient_detail, name="detail"),
    path("<uuid:pk>/edit/", views.patient_update, name="update"),
]

