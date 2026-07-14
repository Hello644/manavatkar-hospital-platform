from django.urls import path

from . import views

app_name = "assist"

urlpatterns = [
    path("visit/<uuid:pk>/<slug:task>/", views.assist_visit, name="assist_visit"),
]
