"""Admin dispatch map, fresh snapshots, safe message drafts, and assignment."""

from urllib.parse import quote

from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from bookings.models import Booking, InstantBookingRequest
from partners.models import PartnerProfile
from services.models import Category, Service

from .. import map_messages
from ..map_data import ACTIVE_STATUSES, booking_data, booking_queryset, candidate_data, dispatch_data, partner_data, partner_queryset
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


@require_POST
@never_cache
def map_assign_partner(request):
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    booking_id, partner_id = request.POST.get("booking_id"), request.POST.get("partner_id")
    service_id = request.POST.get("service_id")
    if not booking_id or not str(partner_id or "").isdecimal() or (service_id and not service_id.isdecimal()):
        return JsonResponse({"success": False, "error": "Select a valid booking and provider."}, status=400)
    with transaction.atomic():
        booking = get_object_or_404(Booking.objects.select_for_update(), booking_id=booking_id)
        is_reassign = request.POST.get("reassign") in ("true", "1", True)
        if booking.status == Booking.Status.CONFIRMED and not is_reassign:
            return JsonResponse({"success": False, "error": "This order is already assigned. Refresh the map."}, status=409)
        if booking.status not in (Booking.Status.PENDING, Booking.Status.SEARCHING, Booking.Status.CONFIRMED) or booking.is_expired:
            return JsonResponse({"success": False, "error": "This order cannot be assigned in its current status. Refresh the map."}, status=409)
        old_provider_id = booking.provider_id
        get_object_or_404(PartnerProfile.objects.select_for_update(), pk=partner_id)
        requested_dates = {booking.scheduled_date or timezone.localdate(), timezone.localdate()}
        partner = get_object_or_404(partner_queryset(requested_dates), pk=partner_id)
        pdata = partner_data(partner)
        candidate = candidate_data(booking, pdata)
        if not candidate["is_eligible"]:
            return JsonResponse({"success": False, "error": "; ".join(candidate["reasons"]) or "No eligible service for this order."}, status=400)
        selected_service_id = int(service_id) if service_id else candidate["service_id"]
        if selected_service_id not in candidate["service_ids"]:
            return JsonResponse({"success": False, "error": "The selected service cannot fulfil this order."}, status=400)
        selected_service = get_object_or_404(Service.objects.select_for_update(), pk=selected_service_id, partner=partner)
        # Recheck after taking the service lock: its availability or unit may
        # have changed since the initial candidate query.
        partner = get_object_or_404(partner_queryset(requested_dates), pk=partner_id)
        current_candidate = candidate_data(booking, partner_data(partner))
        if not current_candidate["is_eligible"] or selected_service_id not in current_candidate["service_ids"]:
            return JsonResponse({"success": False, "error": "This service changed. Refresh the map before assigning."}, status=409)
        # Clean up old provider's busy day reservation if reassigning
        if old_provider_id and old_provider_id != partner.id:
            from availability.models import BusyDay
            BusyDay.objects.filter(booking=booking, partner_id=old_provider_id).delete()
        # Scheduled orders keep their booked asset. Instant orders gain a
        # concrete eligible service while retaining the agreed price snapshot.
        booking.service = selected_service
        booking.provider = partner
        booking.status = Booking.Status.CONFIRMED
        booking.assigned_at = timezone.now()
        booking.accepted_by_agent = request.user
        booking.save()  # The model owns BusyDay synchronization and OTP creation.
        winner = InstantBookingRequest.objects.filter(booking=booking, provider=partner, status="PENDING").order_by("-broadcast_round", "-id").first()
        if winner:
            InstantBookingRequest.objects.filter(pk=winner.pk).update(status="ACCEPTED", responded_at=timezone.now())
        InstantBookingRequest.objects.filter(booking=booking, status="PENDING").update(status="EXPIRED", responded_at=timezone.now())
    fresh = get_object_or_404(booking_queryset(), pk=booking.pk)
    updated = booking_data(fresh, {partner.id: partner_data(get_object_or_404(partner_queryset(), pk=partner.id))})
    return JsonResponse({
        "success": True, "message": f"Successfully assigned {pdata['name']} to Booking #{booking.booking_id}!",
        "provider_name": pdata["name"], "provider_id": partner.id, "provider_phone": pdata["phone"],
        "status": booking.status, "status_label": booking.get_status_display(), "booking": updated,
    })


@require_POST
@never_cache
def map_cancel_booking(request):
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    booking_id = request.POST.get("booking_id")
    reason = (request.POST.get("reason") or "").strip()
    if not booking_id:
        return JsonResponse({"success": False, "error": "Booking ID is required."}, status=400)
    with transaction.atomic():
        booking = get_object_or_404(Booking.objects.select_for_update(), booking_id=booking_id)
        if booking.status in (Booking.Status.CANCELLED, Booking.Status.COMPLETED):
            return JsonResponse({"success": False, "error": f"Booking is already {booking.get_status_display().lower()}."}, status=409)
        booking.status = Booking.Status.CANCELLED
        booking.cancellation_reason = reason or "Cancelled by admin from dispatch map"
        booking.cancelled_by = request.user
        booking.save()  # The model auto-cleans busy days and expires instant requests
    return JsonResponse({
        "success": True,
        "message": f"Booking #{booking.booking_id} cancelled successfully.",
        "booking_id": booking.booking_id,
        "status": booking.status,
    })


@require_POST
@never_cache
def map_complete_booking(request):
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    booking_id = request.POST.get("booking_id")
    otp = (request.POST.get("otp") or "").strip()
    if not booking_id:
        return JsonResponse({"success": False, "error": "Booking ID is required."}, status=400)
    with transaction.atomic():
        booking = get_object_or_404(Booking.objects.select_for_update(), booking_id=booking_id)
        if booking.status == Booking.Status.COMPLETED:
            return JsonResponse({"success": False, "error": "Booking is already completed."}, status=409)
        if booking.status == Booking.Status.CANCELLED:
            return JsonResponse({"success": False, "error": "Cancelled bookings cannot be completed."}, status=409)

        expected_otp = booking.end_job_otp or booking.job_otp or booking.start_job_otp
        if expected_otp and otp != expected_otp:
            return JsonResponse({
                "success": False,
                "error": f"Invalid work completion OTP. Expected: {expected_otp}",
            }, status=400)

        booking.status = Booking.Status.COMPLETED
        booking.work_completed_at = timezone.now()
        if not booking.work_started_at:
            booking.work_started_at = timezone.now()

        if booking.provider:
            booking.provider.jobs_completed += 1
            booking.provider.save(update_fields=["jobs_completed"])

        booking.save()
    return JsonResponse({
        "success": True,
        "message": f"Booking #{booking.booking_id} marked as completed!",
        "booking_id": booking.booking_id,
        "status": booking.status,
    })


