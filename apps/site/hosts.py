"""Host normalisation for the public/clinical split.

This is security-critical and subtle enough to deserve its own module. The
isolation decision is "is this request on a public hostname?", and getting the
comparison wrong in either direction is a bug:

  too strict  -> staff on the LAN lose the clinical app
  too loose   -> patient records answer on the internet

The second is a DPDP-notifiable breach, so when the host cannot be parsed we
fail CLOSED and treat the request as public.

A real bug this module exists to prevent: `Host: manwatkarhospital.in.` — the
trailing dot is the legal fully-qualified form, curl and browsers accept it, and
Django's ALLOWED_HOSTS check strips it before validating. A naive
`request.get_host() in PUBLIC_SITE_HOSTS` therefore does NOT match, the request
falls through as "LAN", and /patients/ answers over the internet. Parsing with
Django's own split_domain_port keeps us bug-for-bug consistent with the check
that already let the request in.
"""

from django.conf import settings
from django.http.request import split_domain_port


def normalise(host):
    """Lowercase, strip the port, strip the trailing dot — Django's own rules."""
    domain, _port = split_domain_port(host or "")
    if domain:
        return domain
    # split_domain_port returns '' for anything failing its validation regex.
    # Do a conservative manual clean rather than silently returning ''.
    return (host or "").split(":")[0].strip().rstrip(".").lower()


def public_hostnames():
    """Every spelling of a public host, including the www./apex counterpart.

    Deriving both directions closes a silent, catastrophic config trap: listing
    only the apex in PUBLIC_SITE_HOSTS while www is in ALLOWED_HOSTS means a
    visit to www.manwatkarhospital.in is treated as a LAN request and serves the
    entire clinical system over the internet. Nothing about that failure is
    visible — the apex looks perfectly correct while www quietly leaks.
    """
    hosts = set()
    for raw in getattr(settings, "PUBLIC_SITE_HOSTS", []):
        if not raw:
            continue
        host = normalise(raw)
        if not host:
            continue
        hosts.add(host)
        if host.startswith("www."):
            hosts.add(host[4:])
        else:
            hosts.add("www." + host)
    return hosts


def is_public_request(request):
    """True when this request arrived on an internet-facing hostname.

    Returns False only when a public hostname list is configured AND this host
    is demonstrably not one of them; an unparseable host with a list configured
    counts as public (fail closed).
    """
    hosts = public_hostnames()
    if not hosts:
        return False  # LAN-only install: the whole app answers everywhere
    try:
        host = normalise(request.get_host())
    except Exception:
        return True  # cannot tell -> assume internet, serve only the public site
    if not host:
        return True
    return host in hosts
