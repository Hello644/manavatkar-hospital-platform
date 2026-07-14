from django.core.management.base import BaseCommand

from apps.prescriptions.models import Drug


# A small starter set of common Indian OPD drugs (general medicine + gynecology).
# The formulary grows from real usage via the composer's free-text fallback.
STARTER = [
    ("Paracetamol", "Dolo", "650 mg", "tablet", Drug.Schedule.OTC, "paracetamol", "1-0-1"),
    ("Paracetamol", "Crocin", "500 mg", "tablet", Drug.Schedule.OTC, "paracetamol", "SOS"),
    ("Amoxicillin+Clavulanate", "Augmentin", "625 mg", "tablet", Drug.Schedule.H, "amoxicillin, clavulanic acid", "1-0-1"),
    ("Azithromycin", "Azithral", "500 mg", "tablet", Drug.Schedule.H, "azithromycin", "1-0-0"),
    ("Cefixime", "Taxim-O", "200 mg", "tablet", Drug.Schedule.H, "cefixime", "1-0-1"),
    ("Pantoprazole", "Pan", "40 mg", "tablet", Drug.Schedule.H, "pantoprazole", "1-0-0"),
    ("Omeprazole", "Omez", "20 mg", "capsule", Drug.Schedule.H, "omeprazole", "1-0-0"),
    ("Ondansetron", "Emeset", "4 mg", "tablet", Drug.Schedule.H, "ondansetron", "1-0-1"),
    ("Diclofenac", "Voveran", "50 mg", "tablet", Drug.Schedule.H, "diclofenac", "1-0-1"),
    ("Ibuprofen", "Brufen", "400 mg", "tablet", Drug.Schedule.OTC, "ibuprofen", "1-0-1"),
    ("Cetirizine", "Cetzine", "10 mg", "tablet", Drug.Schedule.OTC, "cetirizine", "0-0-1"),
    ("Levocetirizine", "Levocet", "5 mg", "tablet", Drug.Schedule.OTC, "levocetirizine", "0-0-1"),
    ("Metformin", "Glycomet", "500 mg", "tablet", Drug.Schedule.H, "metformin", "1-0-1"),
    ("Amlodipine", "Amlong", "5 mg", "tablet", Drug.Schedule.H, "amlodipine", "1-0-0"),
    ("Telmisartan", "Telma", "40 mg", "tablet", Drug.Schedule.H, "telmisartan", "1-0-0"),
    ("Atorvastatin", "Atorva", "10 mg", "tablet", Drug.Schedule.H, "atorvastatin", "0-0-1"),
    ("Iron+Folic acid", "Fefol", "", "capsule", Drug.Schedule.OTC, "ferrous sulphate, folic acid", "0-0-1"),
    ("Folic acid", "Folvite", "5 mg", "tablet", Drug.Schedule.OTC, "folic acid", "1-0-0"),
    ("Calcium+Vitamin D3", "Shelcal", "500 mg", "tablet", Drug.Schedule.OTC, "calcium carbonate, cholecalciferol", "1-0-0"),
    ("Alprazolam", "Alprax", "0.25 mg", "tablet", Drug.Schedule.H1, "alprazolam", "0-0-1"),
    ("Tramadol", "Ultracet", "37.5 mg", "tablet", Drug.Schedule.H1, "tramadol, paracetamol", "1-0-1"),
    ("Metronidazole", "Flagyl", "400 mg", "tablet", Drug.Schedule.H, "metronidazole", "1-1-1"),
]


class Command(BaseCommand):
    help = "Seed the starter OPD formulary (idempotent)."

    def handle(self, *args, **options):
        created = 0
        for generic, brand, strength, form, schedule, ingredients, sig in STARTER:
            _obj, was_created = Drug.objects.get_or_create(
                generic_name=generic,
                brand_name=brand,
                strength=strength,
                form=form,
                defaults={
                    "schedule": schedule,
                    "ingredients": ingredients,
                    "default_sig": sig,
                },
            )
            created += 1 if was_created else 0
        self.stdout.write(
            self.style.SUCCESS(f"Formulary seeded: {created} new, {Drug.objects.count()} total.")
        )
