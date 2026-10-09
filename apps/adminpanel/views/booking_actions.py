"""State changes on a single booking (assign, cancel, complete, retry search).

These JSON endpoints are shared by the dispatch map and the Bookings pages, so
every agent action on a booking goes through one place.
"""

from functools import wraps

from django.db import transaction
from django.db.models import F
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from bookings.instant import InstantBookingError, rebroadcast_instant_booking
from bookings.models import Booking, InstantBookingRequest
from partners.models import PartnerProfile
from services.models import Service

from ..map_data import booking_data, booking_queryset, candidate_data, partner_data, partner_queryset
from ..permissions import is_agent


def _json_404(view):
    """Callers parse JSON, so a missing booking/partner must not return an HTML 404 page."""
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except Http404:
            return JsonResponse({"success": False, "error": "Not found. Refresh and try again."}, status=404)
    return wrapped


@require_POST
@never_cache
@_json_404
def booking_assign_partner(request):
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
@_json_404
def booking_cancel(request):
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
        booking.cancellation_reason = reason or "Cancelled by admin"
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
@_json_404
def booking_complete(request):
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
        if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS) or not booking.provider_id:
            return JsonResponse({"success": False, "error": "Only orders assigned to a provider can be completed."}, status=409)

        expected_otp = booking.end_job_otp or booking.job_otp or booking.start_job_otp
        if expected_otp and otp != expected_otp:
            return JsonResponse({"success": False, "error": "Invalid work completion OTP."}, status=400)

        booking.status = Booking.Status.COMPLETED
        booking.work_completed_at = timezone.now()
        if not booking.work_started_at:
            booking.work_started_at = timezone.now()
        booking.save()
        PartnerProfile.objects.filter(pk=booking.provider_id).update(jobs_completed=F("jobs_completed") + 1)
    return JsonResponse({
        "success": True,
        "message": f"Booking #{booking.booking_id} marked as completed!",
        "booking_id": booking.booking_id,
        "status": booking.status,
    })


@require_POST
@never_cache
@_json_404
def booking_rebroadcast(request):
    """Retry search: notify nearby providers again for an unassigned instant order."""
    if not is_agent(request.user):
        return JsonResponse({"success": False, "error": "Admin access required."}, status=403)
    booking = get_object_or_404(Booking, booking_id=request.POST.get("booking_id") or "")
    try:
        booking, notified = rebroadcast_instant_booking(booking)
    except InstantBookingError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=409)
    return JsonResponse({
        "success": True,
        "message": f"Searching again: {notified} nearby provider{'s' if notified != 1 else ''} notified.",
        "booking_id": booking.booking_id,
        "status": booking.status,
        "providers_notified": notified,
    })
