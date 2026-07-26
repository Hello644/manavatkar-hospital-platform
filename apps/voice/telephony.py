"""Twilio adapter: TwiML builders + request-signature verification. This is the
only provider-specific file — the agent and tools are provider-agnostic."""

import base64
import hashlib
import hmac
from xml.sax.saxutils import escape


def _say(text, voice, language):
    return f'<Say voice="{escape(voice, {chr(34): "&quot;"})}" language="{escape(language)}">{escape(text)}</Say>'


def gather(text, action_url, voice, language):
    """Speak `text`, then listen for the caller's next utterance (speech-to-text)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather input="speech" action="{escape(action_url)}" method="POST" '
        f'speechTimeout="auto" language="{escape(language)}">'
        f"{_say(text, voice, language)}"
        "</Gather>"
        f'{_say("Sorry, I did not catch that. Please call again. Goodbye.", voice, language)}'
        "<Hangup/>"
        "</Response>"
    )


def say_hangup(text, voice, language):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response>{_say(text, voice, language)}<Hangup/></Response>"
    )


def compute_signature(auth_token, url, params):
    payload = url
    for key in sorted(params.keys()):
        payload += key + params[key]
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_signature(auth_token, url, params, signature):
    expected = compute_signature(auth_token, url, params)
    return hmac.compare_digest(expected, signature or "")
