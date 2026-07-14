import os

from django.conf import settings


SYSTEM_PROMPTS = {
    "summary": (
        "You are a clinical assistant for a doctor at an Indian OPD. Summarize the "
        "patient context below into a concise clinical snapshot (problems, relevant "
        "history, current vitals, allergies). Be factual; do not invent data. This is "
        "decision-support only, not a diagnosis."
    ),
    "soap": (
        "You are a clinical scribe. Draft a SOAP note (Subjective, Objective, "
        "Assessment, Plan) from the context below. Use only the information given; "
        "mark gaps as 'not recorded'. Output plain text with S/O/A/P headings. The "
        "doctor will review and edit before it becomes the record."
    ),
    "explain": (
        "You are a clinical assistant. Explain the lab/vitals findings below in plain "
        "clinical language, flagging abnormal values and their likely significance. "
        "Decision-support only; do not prescribe."
    ),
}


def _api_key():
    return settings.OPD_ANTHROPIC_API_KEY or os.environ.get("ANTHROPIC_API_KEY", "")


def is_available():
    """AI assist is opt-in and needs a key and the SDK installed."""
    if not settings.OPD_AI_ENABLED or not _api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def build_context(visit):
    """De-identified clinical context — NO name, UHID, mobile or address leaves
    the building. Age/sex + clinical facts only (DPDP data-minimisation)."""
    patient = visit.patient
    lines = [
        f"Patient: {patient.get_age_years() or '?'}y {patient.get_sex_display()}",
    ]
    allergies = [a.substance for a in patient.allergies.all()]
    if allergies:
        lines.append("Allergies: " + ", ".join(allergies))
    chronic = [c.name for c in patient.chronic_conditions.all()]
    if chronic:
        lines.append("Chronic conditions: " + ", ".join(chronic))

    vitals = getattr(visit, "vitals", None)
    if vitals:
        v = []
        if vitals.weight_kg:
            v.append(f"weight {vitals.weight_kg}kg")
        if vitals.bp_systolic:
            v.append(f"BP {vitals.bp_systolic}/{vitals.bp_diastolic}")
        if vitals.pulse:
            v.append(f"pulse {vitals.pulse}")
        if vitals.spo2:
            v.append(f"SpO2 {vitals.spo2}%")
        if vitals.temp_f:
            v.append(f"temp {vitals.temp_f}F")
        if vitals.rbs:
            v.append(f"RBS {vitals.rbs}")
        if vitals.chief_complaint:
            v.append(f"complaint: {vitals.chief_complaint}")
        if v:
            lines.append("Vitals: " + ", ".join(v))

    note = getattr(visit, "note", None)
    if note and not note.is_empty:
        for label, val in [
            ("Complaint", note.chief_complaint), ("History", note.history),
            ("Examination", note.examination), ("Diagnosis", note.diagnosis),
            ("Assessment", note.assessment), ("Plan", note.plan),
        ]:
            if val:
                lines.append(f"{label}: {val}")

    for order in visit.lab_orders.all():
        results = [
            f"{i.test_text}={i.result_value}{i.result_unit} ({i.flag or 'n/a'})"
            for i in order.items.all() if i.result_value
        ]
        if results:
            lines.append("Lab: " + "; ".join(results))

    past = [
        f"{v.visit_date:%Y-%m}: {v.get_disposition_display()}"
        for v in patient.visits.filter(status="completed").exclude(pk=visit.pk)[:5]
    ]
    if past:
        lines.append("Recent visits: " + "; ".join(past))

    return "\n".join(lines)


def run(task, context):
    """Call Claude for a decision-support draft. Returns (ok, text)."""
    import anthropic

    client = anthropic.Anthropic(api_key=_api_key())
    try:
        message = client.messages.create(
            model=settings.OPD_AI_MODEL,
            max_tokens=2000,
            system=SYSTEM_PROMPTS[task],
            messages=[{"role": "user", "content": context}],
        )
    except anthropic.APIError as exc:
        return False, f"AI service error: {exc}"

    if getattr(message, "stop_reason", None) == "refusal":
        return False, "The AI declined to respond to this request."
    text = "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
    return True, text.strip()
