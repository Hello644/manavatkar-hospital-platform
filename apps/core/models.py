from django.db import models


class HospitalProfile(models.Model):
    """Single, admin-editable record of hospital identity used on the OPD slip,
    the TV token board and (later) the Rx letterhead. Per the owner requirement
    that "nothing that prints is hardcoded", these values live in the DB and are
    editable from the admin — no code change needed to correct an address.
    """

    name = models.CharField(max_length=180, default="Dr. Manavatkar Hospital")
    name_marathi = models.CharField(
        "Name (Marathi)", max_length=180, default="डॉ. मानवतकर हॉस्पिटल", blank=True
    )
    address_line = models.CharField(
        max_length=240, default='"Dattadham", Jamner Road, Bhusawal', blank=True
    )
    phone = models.CharField(max_length=60, default="(02582) 240520", blank=True)
    slip_footer = models.CharField(
        max_length=240,
        default="कृपया आपल्या टोकन क्रमांकाची वाट पहा · Please wait for your token number",
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "hospital profile"
        verbose_name_plural = "hospital profile"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Enforce a singleton row.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        try:
            obj, _created = cls.objects.get_or_create(pk=1)
            return obj
        except Exception:
            # DB unavailable / table not migrated yet — fall back to defaults so
            # the public display never 500s over a masters lookup.
            return cls()
