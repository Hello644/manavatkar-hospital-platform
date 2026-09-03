from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.http import HttpResponse
from django.urls import include, path

from apps.core.views import dashboard, healthz

# The public website (apps.site) owns "/". Everything else here is the clinical
# system and stays LAN-only in production — see the Caddy path allowlist and
# apps.site.middleware.PublicSiteIsolationMiddleware. Adding a route to this
# list does NOT publish it on manwatkarhospital.in.
urlpatterns = [
    path("favicon.ico", lambda request: HttpResponse(status=204), name="favicon"),
    path("healthz/", healthz, name="healthz"),
    path("dashboard/", dashboard, name="dashboard"),
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="accounts/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/", include("apps.accounts.urls")),
    path("patients/", include("apps.patients.urls")),
    path("opd/", include("apps.opd.urls")),
    path("rx/", include("apps.prescriptions.urls")),
    path("comms/", include("apps.comms.urls")),
    path("lab/", include("apps.lab.urls")),
    path("pharmacy/", include("apps.pharmacy.urls")),
    path("assist/", include("apps.assist.urls")),
    path("attendance/", include("apps.attendance.urls")),
    path("voice/", include("apps.voice.urls")),
    # Last: the public site's "" home route must not shadow the paths above.
    path("", include("apps.site.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
