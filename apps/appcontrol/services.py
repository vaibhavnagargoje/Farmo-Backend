"""
Builds what the app and the website should show right now.

`get_state()` is a plain-dict snapshot of maintenance, releases and live
announcements, cached briefly so the middleware can read it on every API
request without a database hit. Saving any app control model clears it.
"""

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from .models import TEXT_LANGUAGES, Announcement, AppControl, AppRelease, Audience

CACHE_KEY = 'appcontrol:state:v1'
CACHE_SECONDS = 30
APP_PLATFORMS = (AppRelease.Platform.ANDROID, AppRelease.Platform.IOS)
WEB = 'web'


def normalize_lang(value):
    """'mr', 'mr-IN', 'hi,en;q=0.8' → a supported language, else 'en'."""
    code = (value or '').split(',')[0].split('-')[0].split(';')[0].strip().lower()
    return code if code in TEXT_LANGUAGES else 'en'


def texts(obj, field):
    """{'en': ..., 'hi': ..., 'mr': ...} for one translatable field."""
    translations = getattr(obj, f'{field}_translations') or {}
    result = {'en': getattr(obj, field) or ''}
    for lang in TEXT_LANGUAGES[1:]:
        if translations.get(lang):
            result[lang] = translations[lang]
    return result


def pick(text_map, lang):
    return text_map.get(lang) or text_map.get('en', '')


def _iso(value):
    return value.isoformat() if value else None


def _snapshot():
    control = AppControl.get()
    now = timezone.now()
    releases = {}
    for release in AppRelease.objects.all():
        releases[release.platform] = {
            'latest_version': release.latest_version,
            'latest_build': release.latest_build,
            'min_supported_build': release.min_supported_build,
            'soft_update_enabled': release.soft_update_enabled,
            'store_url': release.store_url,
            'title': texts(release, 'update_title'),
            'message': texts(release, 'update_message'),
        }
    announcements = []
    live = Announcement.objects.filter(is_active=True, starts_at__lte=now).filter(
        Q(ends_at__isnull=True) | Q(ends_at__gt=now)
    )
    for item in live:
        announcements.append({
            'id': item.id,
            'title': texts(item, 'title'),
            'message': texts(item, 'message'),
            'cta_label': texts(item, 'cta_label'),
            'cta_url': item.cta_url,
            'style': item.style,
            'placement': item.placement,
            'audience': item.audience,
            'show_on': item.show_on,
            'image': item.image.url if item.image else None,
            'dismissible': item.dismissible,
            'ends_at': _iso(item.ends_at),
        })
    return {
        'maintenance': {
            'on': control.maintenance_on,
            'block_api': control.block_api_during_maintenance,
            'ends_at': _iso(control.maintenance_ends_at),
            'title': texts(control, 'maintenance_title'),
            'message': texts(control, 'maintenance_message'),
        },
        'releases': releases,
        'announcements': announcements,
    }


def get_state():
    state = cache.get(CACHE_KEY)
    if state is None:
        state = _snapshot()
        cache.set(CACHE_KEY, state, CACHE_SECONDS)
    return state


def clear_state():
    cache.delete(CACHE_KEY)


def update_status(release, build):
    """'force', 'soft' or 'none' for an installed build number."""
    if not release or build is None:
        return 'none'
    if release['min_supported_build'] and build < release['min_supported_build']:
        return 'force'
    if release['soft_update_enabled'] and release['latest_build'] and build < release['latest_build']:
        return 'soft'
    return 'none'


def maintenance_payload(state, lang):
    m = state['maintenance']
    return {
        'active': m['on'],
        'title': pick(m['title'], lang),
        'message': pick(m['message'], lang),
        'ends_at': m['ends_at'],
    }


def build_config(platform, build, lang, absolute_url=lambda url: url):
    """The full response of GET /api/v1/app/config/."""
    state = get_state()
    result = {'maintenance': maintenance_payload(state, lang), 'update': None}

    if platform in APP_PLATFORMS:
        release = state['releases'].get(platform)
        status = update_status(release, build)
        if release:
            result['update'] = {
                'status': status,
                'latest_version': release['latest_version'],
                'latest_build': release['latest_build'],
                'min_supported_build': release['min_supported_build'],
                'title': pick(release['title'], lang),
                'message': pick(release['message'], lang),
                'store_url': release['store_url'],
            }
        surfaces = (Announcement.ShowOn.APP, Announcement.ShowOn.BOTH)
    else:
        surfaces = (Announcement.ShowOn.WEBSITE, Announcement.ShowOn.BOTH)

    announcements = []
    for item in state['announcements']:
        if item['show_on'] not in surfaces:
            continue
        if platform == WEB and item['audience'] != Audience.ALL:
            continue  # The website has no signed-in farmers or providers.
        announcements.append({
            'id': item['id'],
            'title': pick(item['title'], lang),
            'message': pick(item['message'], lang),
            'cta_label': pick(item['cta_label'], lang),
            'cta_url': item['cta_url'],
            'style': item['style'],
            'placement': item['placement'],
            'audience': item['audience'],
            'image_url': absolute_url(item['image']) if item['image'] else None,
            'dismissible': item['dismissible'],
            'ends_at': item['ends_at'],
        })
    result['announcements'] = announcements
    return result
