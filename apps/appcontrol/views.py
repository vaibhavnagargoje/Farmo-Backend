from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .services import APP_PLATFORMS, WEB, build_config, normalize_lang


class AppConfigView(APIView):
    """
    GET /api/v1/app/config/?platform=android|ios|web&build=27&lang=mr

    What the app or website should show right now: maintenance, whether this
    build must or may update, and live announcements. Public: the app calls it
    before login, and the website calls it from the server.
    """
    permission_classes = [AllowAny]
    authentication_classes = []  # An expired app token must not turn this into a 401.

    def get(self, request):
        platform = (request.query_params.get('platform') or '').lower()
        if platform not in (*APP_PLATFORMS, WEB):
            platform = (request.headers.get('X-App-Platform') or 'android').lower()
            if platform not in (*APP_PLATFORMS, WEB):
                platform = 'android'
        raw_build = request.query_params.get('build') or request.headers.get('X-App-Build') or ''
        build = int(raw_build) if raw_build.isdigit() else None
        lang = normalize_lang(request.query_params.get('lang') or request.headers.get('Accept-Language'))
        return Response(build_config(platform, build, lang, absolute_url=request.build_absolute_uri))
