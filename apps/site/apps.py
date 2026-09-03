from django.apps import AppConfig


class SiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.site"
    label = "publicsite"  # "site" collides with django.contrib.sites' app label
    verbose_name = "Public website"
