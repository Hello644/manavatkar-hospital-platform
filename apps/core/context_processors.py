from .models import HospitalProfile


def hospital(request):
    """Expose the editable hospital identity to every template as ``hospital``."""
    return {"hospital": HospitalProfile.get_solo()}
