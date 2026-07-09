from django.urls import path

from . import views

app_name = "opd"

urlpatterns = [
    path("visits/new/", views.new_visit, name="new_visit"),
    path("visits/<uuid:pk>/slip/", views.visit_slip, name="slip"),
    path("visits/<uuid:pk>/", views.visit_detail, name="visit_detail"),
    path("visits/<uuid:pk>/complete/", views.visit_complete, name="visit_complete"),
    path("visits/<uuid:pk>/action/<slug:action>/", views.queue_action, name="queue_action"),
    path("mlc/quick-register/", views.mlc_quick_register, name="mlc_quick_register"),
    path("board/", views.queue_board, name="queue_board"),
    path("appointments/", views.appointment_list, name="appointments"),
    path("appointments/new/", views.appointment_create, name="appointment_create"),
    path("appointments/<uuid:pk>/cancel/", views.appointment_cancel, name="appointment_cancel"),
    path("appointments/<uuid:pk>/no-show/", views.appointment_no_show, name="appointment_no_show"),
    path("appointments/cancel-day/", views.cancel_day, name="cancel_day"),
    path("queue/redirect/", views.queue_redirect, name="queue_redirect"),
    path("reports/followups/", views.followup_list, name="followup_list"),
    path("vitals/", views.vitals_queue, name="vitals_queue"),
    path("vitals/<uuid:pk>/", views.vitals_entry, name="vitals_entry"),
    path("my-queue/", views.doctor_queue, name="doctor_queue"),
    path("my-queue/call-next/", views.queue_call_next, name="queue_call_next"),
    path("display/", views.display, name="display"),
    path("display/data/", views.display_data, name="display_data"),
    path("reports/collections/", views.collection_register, name="collection_register"),
    path("receipts/<int:pk>/refund/", views.receipt_refund, name="receipt_refund"),
]
