"""
Refuse app API requests during maintenance, and from builds that must update.

Only /api/v1/ is affected. The config endpoint and the admin panel stay
reachable so the app can show why, and admins can turn maintenance off.
Older app versions send no X-App-Build header, so the version check never
touches them; during maintenance their requests fail like any outage.
"""

import logging

from django.http import JsonResponse

from .services import get_state, maintenance_payload, normalize_lang, update_status

logger = logging.getLogger(__name__)

API_PREFIX = '/api/v1/'
EXEMPT_PREFIXES = ('/api/v1/app/', '/api/v1/admin/')


class AppControlMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith(API_PREFIX) and not path.startswith(EXEMPT_PREFIXES) and request.method != 'OPTIONS':
            refusal = self._refusal(request)
            if refusal is not None:
                return refusal
        return self.get_response(request)

    def _refusal(self, request):
        try:
            state = get_state()
        except Exception:  # Never take the API down because this check failed.
            logger.exception('App control state unavailable; allowing request')
            return None

        lang = normalize_lang(request.headers.get('Accept-Language'))
        if state['maintenance']['on'] and state['maintenance']['block_api']:
            maintenance = maintenance_payload(state, lang)
            return JsonResponse({
                'code': 'maintenance',
                'detail': maintenance['message'] or 'Farmo is under maintenance. Please try again soon.',
                'maintenance': maintenance,
            }, status=503)

        platform = (request.headers.get('X-App-Platform') or '').lower()
        build = request.headers.get('X-App-Build') or ''
        release = state['releases'].get(platform)
        if release and build.isdigit() and update_status(release, int(build)) == 'force':
            return JsonResponse({
                'code': 'update_required',
                'detail': 'Please update Farmo to continue.',
                'store_url': release['store_url'],
            }, status=426)
        return None
