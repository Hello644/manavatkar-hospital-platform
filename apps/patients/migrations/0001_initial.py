# Generated for the Phase 0 foundation.
import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Patient",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "uhid",
                    models.CharField(
                        blank=True, editable=False, max_length=20, unique=True
                    ),
                ),
                ("full_name", models.CharField(max_length=180)),
                (
                    "name_normalized",
                    models.CharField(db_index=True, editable=False, max_length=180),
                ),
                ("mobile", models.CharField(blank=True, db_index=True, max_length=10)),
                ("no_phone", models.BooleanField(default=False)),
                ("dob", models.DateField(blank=True, null=True)),
                ("dob_estimated", models.BooleanField(default=False)),
                (
                    "age_years_at_registration",
                    models.PositiveSmallIntegerField(blank=True, null=True),
                ),
                (
                    "sex",
                    models.CharField(
                        choices=[("M", "Male"), ("F", "Female"), ("O", "Other")],
                        max_length=1,
                    ),
                ),
                ("address_line", models.CharField(blank=True, max_length=240)),
                ("area_village", models.CharField(blank=True, max_length=120)),
                (
                    "city",
                    models.CharField(blank=True, default="Bhusawal", max_length=120),
                ),
                (
                    "district",
                    models.CharField(blank=True, default="Jalgaon", max_length=120),
                ),
                ("pincode", models.CharField(blank=True, max_length=6)),
                ("abha_number", models.CharField(blank=True, max_length=32)),
                ("abha_address", models.CharField(blank=True, max_length=120)),
                ("blood_group", models.CharField(blank=True, max_length=8)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("aadhaar_last4", models.CharField(blank=True, max_length=4)),
                (
                    "preferred_language",
                    models.CharField(
                        choices=[
                            ("en", "English"),
                            ("hi", "Hindi"),
                            ("mr", "Marathi"),
                        ],
                        default="mr",
                        max_length=2,
                    ),
                ),
                ("guardian_name", models.CharField(blank=True, max_length=180)),
                (
                    "guardian_relationship",
                    models.CharField(blank=True, max_length=80),
                ),
                (
                    "emergency_contact_name",
                    models.CharField(blank=True, max_length=180),
                ),
                (
                    "emergency_contact_phone",
                    models.CharField(blank=True, max_length=15),
                ),
                ("referral_source", models.CharField(blank=True, max_length=120)),
                (
                    "old_file_number",
                    models.CharField(blank=True, db_index=True, max_length=64),
                ),
                ("privacy_notice_accepted", models.BooleanField(default=False)),
                (
                    "privacy_notice_version",
                    models.CharField(blank=True, max_length=64),
                ),
                ("privacy_notice_accepted_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(default=True)),
                ("soft_deleted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="patients_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "merged_into",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="merged_patients",
                        to="patients.patient",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="patients_updated",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "permissions": [
                    ("merge_patient", "Can merge duplicate patients"),
                    (
                        "view_patient_clinical_summary",
                        "Can view patient clinical summary",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PatientSequence",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("year", models.PositiveSmallIntegerField(unique=True)),
                ("last_value", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-year"]},
        ),
        migrations.CreateModel(
            name="PatientAllergy",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("substance", models.CharField(max_length=120)),
                ("reaction", models.CharField(blank=True, max_length=180)),
                (
                    "severity",
                    models.CharField(
                        choices=[
                            ("mild", "Mild"),
                            ("moderate", "Moderate"),
                            ("severe", "Severe"),
                            ("unknown", "Unknown"),
                        ],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="allergies",
                        to="patients.patient",
                    ),
                ),
            ],
            options={
                "verbose_name_plural": "patient allergies",
                "ordering": ["substance"],
            },
        ),
        migrations.CreateModel(
            name="ChronicCondition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "patient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chronic_conditions",
                        to="patients.patient",
                    ),
                ),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(
                fields=["mobile", "full_name"], name="patients_pa_mobile_ebfce8_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(fields=["uhid"], name="patients_pa_uhid_45d956_idx"),
        ),
        migrations.AddIndex(
            model_name="patient",
            index=models.Index(
                fields=["old_file_number"], name="patients_pa_old_fil_fad33b_idx"
            ),
        ),
    ]
