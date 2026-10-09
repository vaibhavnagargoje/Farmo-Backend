"""Template context shared by every admin panel page."""

from django.conf import settings


def google_maps(request):
    """The Maps key for the location picker in the global Quick Book panel."""
    return {"google_maps_key": settings.GOOGLE_MAPS_API_KEY}
