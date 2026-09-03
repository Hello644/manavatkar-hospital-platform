from django.db import models


class HospitalProfile(models.Model):
    """Single, admin-editable record of hospital identity used on the OPD slip,
    the TV token board, the Rx letterhead and the public website. Per the owner
    requirement that "nothing that prints is hardcoded", these values live in
    the DB and are editable from the admin — no code change needed to correct an
    address, a phone number or the website's opening hours.
    """

    name = models.CharField(max_length=180, default="Manwatkar Hospital")
    name_marathi = models.CharField(
        "Name (Marathi)", max_length=180, default="मानवतकर हॉस्पिटल", blank=True
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

    # ── Public website (apps.site) ───────────────────────────────────────────
    # Everything a visitor to manwatkarhospital.in sees, editable without a
    # deploy. Blank fields are simply omitted from the page rather than shown
    # empty, so the site stays presentable before all of this is filled in.
    tagline = models.CharField(
        max_length=200, blank=True,
        default="Caring for Bhusawal families since 1985",
        help_text="One line under the hospital name on the website home page.",
    )
    about_text = models.TextField(
        blank=True, help_text="A few sentences about the hospital, shown on the website."
    )
    emergency_phone = models.CharField(
        max_length=60, blank=True, help_text="Casualty / 24-hour number, shown prominently."
    )
    whatsapp_number = models.CharField(max_length=20, blank=True)
    public_email = models.EmailField(blank=True)
    opd_hours_text = models.CharField(
        max_length=240, blank=True,
        default="Mon–Sat 10:00–13:00 and 17:00–20:00 · Sunday closed",
        help_text="Human-readable OPD timings for the website and footer.",
    )
    city = models.CharField(max_length=80, blank=True, default="Bhusawal")
    state = models.CharField(max_length=80, blank=True, default="Maharashtra")
    pincode = models.CharField(max_length=10, blank=True)
    map_query = models.CharField(
        max_length=240, blank=True,
        help_text="Address or 'lat,lng' used for the Directions link on the website.",
    )
    website_domain = models.CharField(
        max_length=120, blank=True, default="manwatkarhospital.in",
        help_text="Canonical public domain, used in page metadata.",
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

    @property
    def directions_query(self):
        """What to hand a maps app for the Directions link. Falls back to the
        postal address so the link works before anyone sets coordinates."""
        if self.map_query:
            return self.map_query
        return ", ".join(p for p in [self.name, self.address_line, self.city, self.state] if p)

    @property
    def full_address(self):
        parts = [self.address_line, self.city, self.state, self.pincode]
        return ", ".join(p for p in parts if p)
