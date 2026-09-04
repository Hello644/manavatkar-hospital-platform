"""Booking tools exposed to the voice agent.

The behaviour lives in apps.opd.booking, shared with the public website — this
module only adapts it to the Claude tool-use surface. Names are re-exported so
the agent (and its tests) can keep calling ``tools.available_slots`` etc.
"""

from apps.opd.booking import (  # noqa: F401  (re-exported for the agent + tests)
    SESSIONS,
    available_sessions,
    find_doctors,
    find_patient,
)
from apps.opd.booking import book_appointment as _book_appointment


def book_appointment(patient_name, mobile, doctor_name, date_str, session_key):
    return _book_appointment(
        patient_name, mobile, doctor_name, date_str, session_key, source="AI phone agent"
    )


# ----------------------------------------------------------- agent tool surface

TOOL_SCHEMAS = [
    {
        "name": "find_doctors",
        "description": "List the hospital's doctors, their specialties and consult fees.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "available_sessions",
        "description": (
            "Which OPD sittings run for a doctor on a date. The hospital does NOT "
            "use numbered time slots — patients are booked into a sitting and seen "
            "in token order. Use before booking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "doctor_name": {"type": "string"},
                "date_str": {"type": "string", "description": "'today', 'tomorrow' or YYYY-MM-DD"},
            },
            "required": ["doctor_name", "date_str"],
        },
    },
    {
        "name": "find_patient",
        "description": "Look up an existing patient by mobile number to reuse their record.",
        "input_schema": {
            "type": "object",
            "properties": {"mobile": {"type": "string"}},
            "required": ["mobile"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book once you have name, 10-digit mobile, doctor, date and a sitting "
            "(morning or evening)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "mobile": {"type": "string"},
                "doctor_name": {"type": "string"},
                "date_str": {"type": "string"},
                "session_key": {"type": "string", "enum": ["morning", "evening"]},
            },
            "required": ["patient_name", "mobile", "doctor_name", "date_str", "session_key"],
        },
    },
    {
        "name": "end_call",
        "description": "End the call after confirming a booking or when the caller is done.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
]

DISPATCH = {
    "find_doctors": lambda i: find_doctors(),
    "available_sessions": lambda i: available_sessions(i.get("doctor_name"), i.get("date_str")),
    "find_patient": lambda i: find_patient(i.get("mobile")),
    "book_appointment": lambda i: book_appointment(
        i.get("patient_name"), i.get("mobile"), i.get("doctor_name"),
        i.get("date_str"), i.get("session_key"),
    ),
}


def run_tool(name, tool_input):
    handler = DISPATCH.get(name)
    if handler is None:
        return {"error": f"unknown tool {name}"}
    try:
        return handler(tool_input or {})
    except Exception as exc:
        return {"error": str(exc)}
