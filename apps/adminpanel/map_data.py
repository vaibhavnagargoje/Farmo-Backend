"""Shared, admin-only data and matching rules for the dispatch map."""

import math

from django.db.models import Prefetch, Q
from django.urls import reverse
from django.utils import timezone

from availability.models import BusyDay
from bookings.models import Booking, BookingOffer
from labor_services.models import LaborServiceOffering
from partners.models import PartnerProfile
from services.models import Service, ServicePriceUnit


ACTIVE_STATUSES = ("SEARCHING", "CONFIRMED", "IN_PROGRESS")
ASSIGNED_STATUSES = ("CONFIRMED", "IN_PROGRESS")


def user_name(user):
    profile = getattr(user, "customer_profile", None)
    return (profile.full_name if profile else "") or str(user.phone_number)


def distance_km(lat1, lng1, lat2, lng2):
    """Distance between stored coordinates, never displaced display pins."""
    if any(value is None for value in (lat1, lng1, lat2, lng2)):
        return None
    try:
        a, b, c, d = map(float, (lat1, lng1, lat2, lng2))
        if not all(math.isfinite(value) for value in (a, b, c, d)):
            return None
        if not (-90 <= a <= 90 and -90 <= c <= 90 and -180 <= b <= 180 and -180 <= d <= 180):
            return None
        a, b, c, d = map(math.radians, (a, b, c, d))
        h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
        return 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h))))
    except (TypeError, ValueError):
        return None


def partner_queryset(busy_dates=None):
    busy_days = BusyDay.objects.filter(date__in=busy_dates) if busy_dates is not None else BusyDay.objects.filter(date__gte=timezone.localdate())
    return PartnerProfile.objects.select_related(
        "user", "user__location", "user__customer_profile"
    ).prefetch_related(
        Prefetch("services", queryset=Service.objects.filter(status=Service.Status.ACTIVE).select_related("category", "price_unit")),
        Prefetch("busy_days", queryset=busy_days),
        Prefetch("labor_details__offerings", queryset=LaborServiceOffering.objects.select_related("service_type__category", "price_unit")),
    )


def partner_data(partner):
    loc = getattr(partner.user, "location", None)
    partner_days = set()
    asset_days = {}
    for day in partner.busy_days.all():
        if day.service_id is None:
            partner_days.add(day.date.isoformat())
        else:
            asset_days.setdefault(day.service_id, set()).add(day.date.isoformat())
    services = []
    for service in partner.services.all():
        if service.status != Service.Status.ACTIVE:
            continue
        services.append({
            "id": service.id, "title": service.title,
            "category_id": service.category_id, "category_name": service.category.name,
            "category_active": service.category.is_active,
            "price": float(service.price), "price_unit": service.price_unit.key,
            "price_unit_label": service.price_unit.name, "min_order_qty": float(service.min_order_qty),
            "is_available": service.is_available, "radius_km": service.service_radius_km,
            "busy_dates": sorted(asset_days.get(service.id, set())),
        })
    details = getattr(partner, "labor_details", None)
    offerings = [{
        "id": offering.id, "title": offering.service_type.name,
        "category_id": offering.service_type.category_id,
        "category_name": offering.service_type.category.name,
        "price": float(offering.price), "price_unit_label": offering.price_unit.name,
        "note": offering.note,
    } for offering in details.offerings.all()] if details else []
    return {
        "id": partner.id,
        "name": partner.business_name or user_name(partner.user),
        "phone": str(partner.user.phone_number),
        "type_label": partner.get_partner_type_display(),
        "lat": float(loc.latitude) if loc and loc.latitude is not None else None,
        "lng": float(loc.longitude) if loc and loc.longitude is not None else None,
        "radius_km": max((service["radius_km"] for service in services), default=10),
        "is_available": partner.is_available, "is_active": partner.user.is_active,
        "is_busy_today": timezone.localdate().isoformat() in partner_days,
        "busy_dates": sorted(partner_days), "is_verified": partner.is_verified,
        "jobs_completed": partner.jobs_completed, "rating": float(partner.rating),
        "services": [service["title"] for service in services] + [offering["title"] for offering in offerings],
        "service_details": services, "labor_offerings": offerings,
        "profile_url": reverse("adminpanel:user-detail", kwargs={"user_id": partner.user_id}),
    }


def candidate_data(booking, partner):
    """Matching metadata used both by rendering and assignment validation."""
    category_id = booking.category_id or (booking.service.category_id if booking.service_id else None)
    target_date = (booking.scheduled_date or timezone.localdate()).isoformat()
    dist = distance_km(booking.lat, booking.lng, partner["lat"], partner["lng"])
    reasons = []
    if not partner["is_active"]:
        reasons.append("Account inactive")
    if not partner["is_available"]:
        reasons.append("Partner offline")
    partner_busy = target_date in partner["busy_dates"]
    if partner_busy:
        reasons.append("Partner busy on requested date")
    if dist is None:
        reasons.append("Location unavailable")
    services = [service for service in partner["service_details"] if service["category_id"] == category_id]
    if not services:
        reasons.append("No matching service category")
    eligible = []
    service_reasons = []
    for service in services:
        problems = []
        if not service["category_active"]:
            problems.append("Service category inactive")
        if not service["is_available"]:
            problems.append("Service unavailable")
        if target_date in service["busy_dates"]:
            problems.append("Machine busy on requested date")
        if service["price_unit"] != booking.price_unit:
            problems.append("Pricing unit differs from order")
        if float(booking.quantity) < service["min_order_qty"]:
            problems.append("Quantity below service minimum")
        if dist is not None and dist > service["radius_km"]:
            problems.append("Outside service radius")
        if problems:
            service_reasons.extend(problems)
        else:
            eligible.append(service)
    if not eligible:
        reasons.extend(dict.fromkeys(service_reasons))
    in_coverage = dist is not None and any(dist <= service["radius_km"] for service in services)
    return {
        "provider_id": partner["id"], "distance_km": round(dist, 2) if dist is not None else None,
        "in_coverage": in_coverage, "is_eligible": bool(eligible) and not reasons,
        "is_busy_on_date": partner_busy or bool(services) and all(target_date in service["busy_dates"] for service in services),
        "service_id": eligible[0]["id"] if eligible else None,
        "service_ids": [service["id"] for service in eligible], "reasons": list(dict.fromkeys(reasons)),
    }


def booking_queryset():
    return Booking.objects.select_related(
        "customer__customer_profile", "category", "service__category", "provider__user__customer_profile"
    ).prefetch_related(Prefetch("offers", queryset=BookingOffer.objects.order_by("provider_id", "-broadcast_round", "-id")))


def booking_data(booking, partners, unit_labels=None):
    service = booking.service
    category = booking.category or (service.category if service else None)
    assigned = partners.get(booking.provider_id)
    accepted_id = booking.provider_id if booking.status in ASSIGNED_STATUSES else None
    requests = []
    seen = set()
    for item in booking.offers.all():
        if item.provider_id in seen:
            continue
        seen.add(item.provider_id)
        requests.append({
            "id": item.id, "provider_id": item.provider_id, "status": item.status,
            "status_label": item.get_status_display(), "broadcast_round": item.broadcast_round,
            "distance_km": float(item.distance_km) if item.distance_km is not None else None,
            "notified_at": item.notified_at.isoformat(),
            "responded_at": item.responded_at.isoformat() if item.responded_at else None,
            "response_deadline": item.response_deadline.isoformat() if item.response_deadline else None,
            "is_winner": item.provider_id == accepted_id,
        })
    return {
        "id": booking.id, "booking_id": booking.booking_id, "order_number": booking.order_number or "",
        "customer_name": user_name(booking.customer),
        "customer_phone": str(booking.customer.phone_number),
        "customer_profile_url": reverse("adminpanel:user-detail", kwargs={"user_id": booking.customer_id}),
        "service_id": booking.service_id, "service_name": service.title if service else (category.name if category else ""),
        "category_id": category.id if category else None, "category_name": category.name if category else "",
        "status": booking.status, "status_label": booking.get_status_display(), "is_phone": bool(booking.created_by_agent_id),
        "lat": float(booking.lat) if booking.lat is not None else None,
        "lng": float(booking.lng) if booking.lng is not None else None, "address": booking.address or "",
        "scheduled_date": booking.scheduled_date.isoformat() if booking.scheduled_date else "",
        "scheduled_time": booking.scheduled_time.strftime("%I:%M %p") if booking.scheduled_time else "",
        "created_at": timezone.localtime(booking.created_at).strftime("%d %b %Y, %I:%M %p"),
        "updated_at": booking.updated_at.isoformat(), "expires_at": booking.expires_at.isoformat() if booking.expires_at else None,
        "quantity": float(booking.quantity), "price_unit": booking.price_unit,
        "price_unit_label": (unit_labels or {}).get(booking.price_unit, booking.price_unit),
        "unit_price": float(booking.unit_price or 0), "discount_amount": float(booking.discount_amount or 0),
        "total_amount": float(booking.total_amount or 0),
        "note": booking.note or "", "provider_id": booking.provider_id,
        "provider_name": assigned["name"] if assigned else None,
        "provider_phone": assigned["phone"] if assigned else None,
        "provider_profile_url": assigned["profile_url"] if assigned else None,
        "assigned_provider": assigned, "accepted_provider_id": accepted_id, "requests": requests,
        "message_url": reverse("adminpanel:map-message-draft"),
        "candidates": [candidate_data(booking, partner) for partner in partners.values()],
        "start_job_otp": booking.start_job_otp or "",
        "end_job_otp": booking.end_job_otp or "",
        "job_otp": booking.job_otp or "",
        "otp_mode_snapshot": booking.otp_mode_snapshot or "",
        "completion_otp": booking.end_job_otp or booking.job_otp or "",
        "cancellation_reason": booking.cancellation_reason or "",
    }


def dispatch_data(category_filter="", status_filter=""):
    bookings = booking_queryset().filter(status__in=[status_filter] if status_filter else ACTIVE_STATUSES, lat__isnull=False, lng__isnull=False)
    if category_filter:
        bookings = bookings.filter(Q(category_id=category_filter) | Q(service__category_id=category_filter))
    bookings = list(bookings)
    relevant_dates = {booking.scheduled_date for booking in bookings if booking.scheduled_date}
    relevant_dates.add(timezone.localdate())
    partners = {partner.id: partner_data(partner) for partner in partner_queryset(relevant_dates)}
    units = dict(ServicePriceUnit.objects.values_list("key", "name"))
    orders = [booking_data(booking, partners, units) for booking in bookings]
    visible = [partner for partner in partners.values() if partner["lat"] is not None and partner["lng"] is not None
               and (not category_filter or any(str(service["category_id"]) == str(category_filter) for service in partner["service_details"]))]
    counts = {}
    for booking in Booking.objects.filter(status__in=ACTIVE_STATUSES).select_related("service"):
        category_id = booking.category_id or (booking.service.category_id if booking.service_id else None)
        if category_id:
            counts[category_id] = counts.get(category_id, 0) + 1
    return {
        "partners": visible, "bookings": orders, "updated_at": timezone.now().isoformat(),
        "stats": {
            "total_partners_on_map": len(visible), "total_bookings_on_map": len(orders),
            "pending_bookings_count": sum(booking["status"] == "SEARCHING" for booking in orders),
            "partners_online_count": sum(partner["is_available"] and partner["is_active"] for partner in visible),
            "partners_without_location": sum(partner["lat"] is None or partner["lng"] is None for partner in partners.values()),
            "booking_counts_by_category": counts, "total_active_bookings": sum(counts.values()),
        },
    }
