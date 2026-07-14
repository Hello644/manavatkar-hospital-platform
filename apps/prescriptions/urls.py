from django.urls import path

from . import views

app_name = "prescriptions"

urlpatterns = [
    path("visit/<uuid:visit_pk>/new/", views.compose, name="compose"),
    path("formulary/search/", views.formulary_search, name="formulary_search"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/print/", views.print_view, name="print"),
]
