from django.shortcuts import redirect


class ForcePinChangeMiddleware:
    """When an admin forces a PIN reset (``must_change_pin``), hold the user on
    the Set-PIN page until they pick a new one. Without this the flag was
    written but never honoured."""

    EXEMPT_PREFIXES = ("/accounts/set-pin", "/logout", "/static", "/media", "/admin")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_pin", False)
            and not request.path.startswith(self.EXEMPT_PREFIXES)
        ):
            return redirect("accounts:set_pin")
        return self.get_response(request)
