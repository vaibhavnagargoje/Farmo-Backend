"""Admin dispatch map, fresh snapshots, and safe message drafts.

State changes (assign, cancel, complete) live in booking_actions.py.
"""

from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from bookings.models import Booking
from partners.models import PartnerProfile
from services.models import Category

from .. import map_messages
from ..map_data import ACTIVE_STATUSES, booking_queryset, dispatch_data
from ..permissions import is_agent


def _filters(request):
    category = request.GET.get("category", "")
    status = request.GET.get("status", "")
    return category if category.isdecimal() else "", status if status in Booking.Status.values else ""


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_GET
@never_cache
def map_view(request):
    category, status = _filters(request)
    data = dispatch_data(category, status)
    counts = data["stats"].get("booking_counts_by_category", {})
    categories = list(Category.objects.filter(is_active=True))
    for cat in categories:
        cat.active_booking_count = counts.get(cat.id, 0)
    categories.sort(key=lambda c: (-c.active_booking_count, c.name.lower()))
    return render(request, "adminpanel/map_view.html", {
        "page_title": "Map View", "categories": categories,
        "category_filter": category, "status_filter": status,
        "partners_data": data["partners"], "bookings_data": data["bookings"],
        "google_maps_key": settings.GOOGLE_MAPS_API_KEY, **data["stats"],
    })



@require_GET
@never_cache
def map_data(request):
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    category, status = _filters(request)
    return JsonResponse({"success": True, **dispatch_data(category, status)})


@require_POST
@never_cache
def map_message_draft(request):
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    booking_id, partner_id = request.POST.get("booking_id"), request.POST.get("partner_id")
    if not booking_id or not str(partner_id or "").isdecimal():
        return JsonResponse({"success": False, "error": "Select a booking and provider."}, status=400)
    booking = get_object_or_404(booking_queryset(), booking_id=booking_id)
    partner = get_object_or_404(PartnerProfile.objects.select_related("user__location"), pk=partner_id)
    if booking.status not in ACTIVE_STATUSES or booking.is_expired:
        return JsonResponse({"success": False, "error": "This order is no longer active. Refresh the map."}, status=409)
    phone = map_messages.normalized_phone(partner.user.phone_number)
    if not phone:
        return JsonResponse({"success": False, "error": "This provider has no valid messaging phone number."}, status=400)
    area = map_messages.coarse_area_label(booking.lat, booking.lng)
    # Geocoding can take a moment: enforce disclosure against the latest state.
    booking = get_object_or_404(booking_queryset(), booking_id=booking_id)
    if booking.status not in ACTIVE_STATUSES or booking.is_expired:
        return JsonResponse({"success": False, "error": "This order changed. Refresh the map before messaging."}, status=409)
    text, detail_level, dist = map_messages.build_message(booking, partner, area)
    return JsonResponse({
        "success": True, "text": text, "phone": phone,
        "whatsapp_url": f"https://wa.me/{phone}?text={quote(text, safe='')}",
        "sms_url": f"sms:+{phone}?body={quote(text, safe='')}",
        "detail_level": detail_level, "distance_km": dist, "area_label": area,
        "area_available": bool(area), "booking_status": booking.status,
        "provider_id": booking.provider_id, "updated_at": booking.updated_at.isoformat(),
    })
