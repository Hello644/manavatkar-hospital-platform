"""Cache-busting for static assets during development.

In production WhiteNoise's manifest storage hashes every filename, so a changed
stylesheet arrives under a new URL and no browser can serve a stale copy. In
DEBUG the URL stays /static/css/site.css forever, and a browser that once
cached a failed or empty response for it will keep showing an unstyled page
without ever asking the server again. That happened: the server logged
GET / 200 with no request for the stylesheet at all.

Appending the file's modification time gives the same guarantee in dev.
"""

from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def versioned_static(path):
    url = static(path)
    if not settings.DEBUG:
        return url  # manifest storage already hashes the name
    for directory in settings.STATICFILES_DIRS:
        candidate = Path(directory) / path
        if candidate.exists():
            return f"{url}?v={int(candidate.stat().st_mtime)}"
    return url
