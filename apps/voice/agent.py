"""The conversational booking agent — a Claude tool-use loop. State lives on the
CallSession and is replayed each webhook turn. The Anthropic client is injectable
so the loop is testable without the network."""

import json

from django.conf import settings
from django.utils import timezone

from . import tools

SYSTEM = (
    "You are the phone receptionist for {hospital}. Speak briefly and warmly, like "
    "a real receptionist on a call — one or two short sentences per turn. Your job is "
    "to book an OPD appointment.\n\n"
    "Collect: the patient's name, a 10-digit mobile number, which doctor (or the "
    "problem — then use find_doctors and suggest one), and a preferred day and "
    "sitting. We do NOT give numbered appointment times — patients come during a "
    "sitting and are seen in token order, so offer 'morning' or 'evening' and say "
    "the hours. Use available_sessions to check which sittings actually run that "
    "day; never invent one. Read the mobile number back to confirm before booking. "
    "After book_appointment succeeds, say the confirmed details out loud, then "
    "call end_call.\n\n"
    "Casualty is open 24 hours. For medical advice or emergencies, tell them to come "
    "to casualty straight away, then end_call. Reply in the caller's language (English, Hindi "
    "or Marathi). Keep it natural for text-to-speech: no lists, no markdown."
)


def is_available():
    if not settings.VOICE_AGENT_ENABLED:
        return False
    from apps.assist.services import _api_key

    if not _api_key():
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def _client():
    import anthropic

    from apps.assist.services import _api_key

    return anthropic.Anthropic(api_key=_api_key())


def _blocks_to_dicts(content):
    out = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype == "text":
            out.append({"type": "text", "text": block.text})
        elif btype == "tool_use":
            out.append({"type": "tool_use", "id": block.id, "name": block.name, "input": block.input})
    return out


def _attach_booking(session, result):
    session.booked_appointment_id = result.get("appointment_id")
    session.patient_id = result.get("patient_id")


def respond(session, user_text, client=None, max_iterations=6):
    """Advance the conversation by one caller utterance. Returns (reply, done)."""
    from apps.core.models import HospitalProfile

    system = SYSTEM.format(hospital=HospitalProfile.get_solo().name)
    messages = list(session.messages)
    messages.append({"role": "user", "content": user_text})
    client = client or _client()

    reply_parts = []
    done = False
    for _ in range(max_iterations):
        response = client.messages.create(
            model=settings.VOICE_AGENT_MODEL,
            max_tokens=1024,
            system=system,
            messages=messages,
            tools=tools.TOOL_SCHEMAS,
        )
        blocks = _blocks_to_dicts(response.content)
        text_blocks = [b for b in blocks if b["type"] == "text"]

        if response.stop_reason == "tool_use":
            # Complete tool-call turn: persist ALL blocks (each tool_use must stay
            # paired with the tool_result we send back), run tools, continue.
            messages.append({"role": "assistant", "content": blocks})
            reply_parts += [b["text"] for b in text_blocks]
            tool_results = []
            for block in blocks:
                if block["type"] != "tool_use":
                    continue
                if block["name"] == "end_call":
                    done = True
                    tool_results.append({"type": "tool_result", "tool_use_id": block["id"], "content": "ok"})
                    continue
                result = tools.run_tool(block["name"], block.get("input", {}))
                if block["name"] == "book_appointment" and isinstance(result, dict) and result.get("ok"):
                    _attach_booking(session, result)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block["id"], "content": json.dumps(result)}
                )
            messages.append({"role": "user", "content": tool_results})
            if done:
                break
        else:
            # end_turn / max_tokens / refusal: persist ONLY text so we never leave
            # a dangling tool_use (which would 400 on the next turn's replay); an
            # empty turn persists nothing and falls back to the default reply.
            if text_blocks:
                messages.append({"role": "assistant", "content": text_blocks})
                reply_parts += [b["text"] for b in text_blocks]
            break

    session.messages = messages
    session.turns += 1
    session.save(update_fields=["messages", "turns", "patient", "booked_appointment"])
    reply = " ".join(p.strip() for p in reply_parts if p.strip())
    return reply or "Sorry, could you say that again?", done
