from django.urls import path

from . import views

app_name = "lab"

urlpatterns = [
    path("visit/<uuid:visit_pk>/order/", views.order_create, name="order_create"),
    path("tests/search/", views.test_search, name="test_search"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/results/", views.save_results, name="save_results"),
    path("<uuid:pk>/status/<slug:status>/", views.set_status, name="set_status"),
]
