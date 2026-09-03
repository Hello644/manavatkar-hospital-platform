from django.urls import path

from . import views

app_name = "site"

urlpatterns = [
    path("", views.home, name="home"),
    path("doctors/", views.doctors, name="doctors"),
    path("services/", views.services, name="services"),
    path("contact/", views.contact, name="contact"),
    path("book/", views.book, name="book"),
    path("book/done/", views.book_done, name="book_done"),
    path("robots.txt", views.robots, name="robots"),
    path("sitemap.xml", views.sitemap, name="sitemap"),
]
