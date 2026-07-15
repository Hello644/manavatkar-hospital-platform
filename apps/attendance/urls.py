from django.urls import path

from . import views

app_name = "attendance"

urlpatterns = [
    path("kiosk/", views.kiosk, name="kiosk"),
    path("punch/", views.punch, name="punch"),
    path("board/", views.board, name="board"),
    path("today/", views.today, name="today"),
    path("register/", views.register, name="register"),
    path("register/export/", views.payroll_export, name="payroll_export"),
    path("regularization/", views.regularization_queue, name="regularization"),
    path("regularization/<uuid:pk>/resolve/", views.regularization_resolve, name="regularization_resolve"),
    path("leave/", views.leave_queue, name="leave_queue"),
    path("leave/<uuid:pk>/decide/", views.leave_decide, name="leave_decide"),
    path("enroll/<uuid:staff_id>/", views.enroll, name="enroll"),
]
