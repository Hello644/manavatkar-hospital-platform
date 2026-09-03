from django.conf import settings


def public_site(request):
    """Tell templates whether this request came in over the internet.

    The public templates use it to hide the staff-login link: on
    manwatkarhospital.in there is no reason to advertise where the clinical
    system lives, while on the LAN the same footer gives staff a way in.
    """
    hosts = {h.lower() for h in getattr(settings, "PUBLIC_SITE_HOSTS", [])}
    host = request.get_host().split(":")[0].lower() if hasattr(request, "get_host") else ""
    return {"is_public_host": bool(hosts) and host in hosts}
