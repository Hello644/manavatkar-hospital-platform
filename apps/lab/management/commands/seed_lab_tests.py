from django.core.management.base import BaseCommand

from apps.lab.models import LabTest


# name, short_code, category, sample_type, default_unit, reference_range
STARTER = [
    ("Complete Blood Count", "CBC", "Haematology", "blood", "", ""),
    ("Haemoglobin", "Hb", "Haematology", "blood", "g/dL", "12-16"),
    ("Random Blood Sugar", "RBS", "Biochemistry", "blood", "mg/dL", "70-140"),
    ("Fasting Blood Sugar", "FBS", "Biochemistry", "blood", "mg/dL", "70-100"),
    ("Postprandial Blood Sugar", "PPBS", "Biochemistry", "blood", "mg/dL", "<140"),
    ("Glycated Haemoglobin", "HbA1c", "Biochemistry", "blood", "%", "<5.7"),
    ("Lipid Profile", "LIPID", "Biochemistry", "blood", "", ""),
    ("Liver Function Test", "LFT", "Biochemistry", "blood", "", ""),
    ("Kidney Function Test", "KFT", "Biochemistry", "blood", "", ""),
    ("Serum Creatinine", "CREAT", "Biochemistry", "blood", "mg/dL", "0.6-1.2"),
    ("Thyroid Stimulating Hormone", "TSH", "Endocrinology", "blood", "mIU/L", "0.4-4.0"),
    ("Urine Routine", "URINE-R", "Pathology", "urine", "", ""),
    ("Serum Electrolytes", "LYTES", "Biochemistry", "blood", "", ""),
    ("C-Reactive Protein", "CRP", "Immunology", "blood", "mg/L", "<5"),
    ("Dengue NS1 Antigen", "DENGUE", "Serology", "blood", "", ""),
    ("Urine Pregnancy Test", "UPT", "Pathology", "urine", "", ""),
]


class Command(BaseCommand):
    help = "Seed the starter lab test catalog (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for name, code, category, sample, unit, ref in STARTER:
            _obj, was_created = LabTest.objects.get_or_create(
                name=name,
                defaults={
                    "short_code": code, "category": category, "sample_type": sample,
                    "default_unit": unit, "reference_range": ref,
                },
            )
            created += 1 if was_created else 0
        self.stdout.write(
            self.style.SUCCESS(f"Lab tests seeded: {created} new, {LabTest.objects.count()} total.")
        )
