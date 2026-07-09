"""Server-driven ESC/POS token slip for a thermal printer (Epson TM-T82 / TVS
RP 3230 class). Builds the raw command stream in pure Python — testable without
hardware — and can stream it to a network printer on port 9100 or hand it to a
local spooler as a download.

Devanagari does not render on ASCII ESC/POS firmware, so the thermal slip uses
the hospital's Latin-script name/address; the full A4 slip keeps Marathi.
"""

import socket

from django.utils import timezone


ESC = b"\x1b"
GS = b"\x1d"

INIT = ESC + b"@"
ALIGN_LEFT = ESC + b"a\x00"
ALIGN_CENTER = ESC + b"a\x01"
BOLD_ON = ESC + b"E\x01"
BOLD_OFF = ESC + b"E\x00"
SIZE_NORMAL = GS + b"!\x00"
SIZE_DOUBLE = GS + b"!\x11"  # 2x width + height
SIZE_TRIPLE = GS + b"!\x22"  # 3x width + height (token)
FULL_CUT = GS + b"V\x00"


def _line(text=""):
    return str(text).encode("ascii", "replace") + b"\n"


def build_token_slip(visit, hospital):
    """Return the ESC/POS byte stream for a patient's OPD token."""
    parts = [INIT, ALIGN_CENTER, BOLD_ON, SIZE_DOUBLE, _line(hospital.name)]
    parts += [SIZE_NORMAL, BOLD_OFF]
    if hospital.address_line:
        parts.append(_line(hospital.address_line))
    if hospital.phone:
        parts.append(_line(hospital.phone))
    parts.append(_line())

    if visit.is_mlc:
        parts += [BOLD_ON, _line("*** MEDICO-LEGAL CASE ***"), BOLD_OFF]

    parts += [SIZE_TRIPLE, BOLD_ON, _line(visit.token_label), SIZE_NORMAL, BOLD_OFF]

    parts.append(ALIGN_LEFT)
    parts.append(_line("Patient: " + visit.patient.full_name))
    parts.append(_line("UHID: " + visit.patient.uhid))
    age = visit.patient.get_age_years()
    parts.append(
        _line("Age/Sex: {}/{}".format(age if age is not None else "-", visit.patient.get_sex_display()))
    )
    room = " (Room {})".format(visit.doctor.room_label) if visit.doctor.room_label else ""
    parts.append(_line("Doctor: " + visit.doctor.display_name + room))
    parts.append(_line("Date: " + timezone.localtime(visit.registered_at).strftime("%d-%m-%Y %H:%M")))
    if visit.is_emergency:
        parts += [BOLD_ON, _line("PRIORITY: EMERGENCY"), BOLD_OFF]

    parts.append(_line())
    parts += [ALIGN_CENTER, _line("Please wait for your token"), b"\n\n\n", FULL_CUT]
    return b"".join(parts)


def send_to_printer(payload, host, port=9100, timeout=5):
    """Stream raw ESC/POS bytes to a network thermal printer (RAW/JetDirect 9100)."""
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(payload)
