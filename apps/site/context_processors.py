from .hosts import is_public_request


def public_site(request):
    """Tell templates whether this request came in over the internet.

    The public templates use it to hide the staff-login link: on
    manwatkarhospital.in there is no reason to advertise where the clinical
    system lives, while on the LAN the same footer gives staff a way in.
    """
    return {"is_public_host": is_public_request(request)}
