from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.stock_list, name="stock_list"),
    path("add/", views.stock_add, name="stock_add"),
    path("<uuid:pk>/move/", views.stock_move, name="stock_move"),
    path("dispense/rx/<uuid:rx_pk>/", views.dispense, name="dispense"),
]
