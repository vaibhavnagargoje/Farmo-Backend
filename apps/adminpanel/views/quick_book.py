"""Quick Book: JSON endpoints behind the global slide-over booking wizard.

An agent on a phone call finds or creates the caller, pins the job location,
picks a category and places an INSTANT booking. Creation goes through
bookings.instant, so the order is priced and broadcast exactly like one placed
in the app.
"""

import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from bookings.instant import (
    ACTIVE_INSTANT_STATUSES,
    InstantBookingError,
    active_instant_booking,
    count_nearby_partners,
    create_instant_booking,
)
from bookings.models import Booking
from locations.models import UserLocation
from locations.pricing import resolve_instant_price_detail
from services.models import Category
from users.models import CustomerProfile, User

from ..helpers import find_user_by_phone, normalize_phone
from ..permissions import is_agent

MAX_RESULTS = 8
MAX_QUANTITY = 10000
MAX_UNIT_PRICE = Decimal("10000000")


def _error(message, status=400, **extra):
    return JsonResponse({"success": False, "error": message, **extra}, status=status)


def _forbidden():
    return _error("Admin access required.", status=403)


def _parse_coords(lat, lng):
    """Validated (lat, lng) rounded to the model's 6 decimals, or None."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 6), round(lng, 6)


def _parse_uuid(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _display_name(user):
    profile = getattr(user, "customer_profile", None)
    partner = getattr(user, "partner_profile", None)
    return (
        (profile.full_name if profile else "")
        or (partner.business_name if partner else "")
        or user.get_full_name()
    )


def _booking_summary(booking):
    return {
        "booking_id": booking.booking_id,
        "category": booking.category.name if booking.category else "",
        "status": booking.status,
        "status_label": booking.get_status_display(),
        "url": reverse("adminpanel:booking-detail", kwargs={"booking_id": booking.booking_id}),
    }


def _user_payload(user, active_bookings):
    location = getattr(user, "location", None)
    return {
        "id": str(user.id),
        "phone": user.phone_number,
        "name": _display_name(user),
        "role": user.role,
        "role_label": user.get_role_display(),
        "is_active": user.is_active,
        "address": location.address if location else "",
        "lat": float(location.latitude) if location and location.latitude is not None else None,
        "lng": float(location.longitude) if location and location.longitude is not None else None,
        "active_bookings": [_booking_summary(b) for b in active_bookings],
    }


@require_GET
@never_cache
def quick_book_user_search(request):
    """Find callers by phone digits (any stored format) or by name."""
    if not is_agent(request.user):
        return _forbidden()
    query = (request.GET.get("q") or "").strip()
    digits = re.sub(r"\D", "", query)
    if digits and not re.sub(r"[\d\s+\-()]", "", query):
        if len(digits) < 3:
            return JsonResponse({"success": True, "users": []})
        # Match on the last ten digits so 98765… finds +9198765… and vice versa.
        users = User.objects.filter(phone_number__contains=digits[-10:])
    elif len(query) >= 2:
        users = User.objects.filter(
            Q(customer_profile__full_name__icontains=query)
            | Q(partner_profile__business_name__icontains=query)
        )
    else:
        return JsonResponse({"success": True, "users": []})

    users = list(
        users.select_related("customer_profile", "partner_profile", "location")
        .order_by("-date_joined").distinct()[:MAX_RESULTS]
    )
    active = {}
    for booking in Booking.objects.filter(
        customer__in=users, booking_type=Booking.BookingType.INSTANT, status__in=ACTIVE_INSTANT_STATUSES,
    ).select_related("category").order_by("-created_at"):
        active.setdefault(booking.customer_id, []).append(booking)
    return JsonResponse({
        "success": True,
        "users": [_user_payload(u, active.get(u.id, [])) for u in users],
    })


@require_GET
@never_cache
def quick_book_categories(request):
    """
    Instant-enabled categories. With ``lat``/``lng`` each one carries the
    price for that spot (pricing zone aware) and how many providers would be
    notified; with ``customer_id`` it also flags an open order in that category.
    """
    if not is_agent(request.user):
        return _forbidden()
    coords = _parse_coords(request.GET.get("lat"), request.GET.get("lng"))
    customer_id = _parse_uuid(request.GET.get("customer_id"))
    open_orders = {}
    if customer_id:
        for booking in Booking.objects.filter(
            customer_id=customer_id, booking_type=Booking.BookingType.INSTANT, status__in=ACTIVE_INSTANT_STATUSES,
        ).select_related("category"):
            open_orders.setdefault(booking.category_id, booking)

    categories = []
    for category in Category.objects.filter(is_active=True, instant_enabled=True).select_related(
        "instant_price_unit"
    ).order_by("name"):
        if coords:
            price, unit, zone_name = resolve_instant_price_detail(category, *coords)
            providers_nearby = count_nearby_partners(category, *coords)
        else:
            price, unit, zone_name = float(category.instant_price or 0), category.instant_price_unit, None
            providers_nearby = None
        open_order = open_orders.get(category.id)
        categories.append({
            "id": category.id,
            "name": category.name,
            "price": price,
            "price_unit_key": unit.key if unit else "HOUR",
            "price_unit": unit.name if unit else "Per Hour",
            "zone_name": zone_name,
            "providers_nearby": providers_nearby,
            "radius_km": category.instant_search_radius_km,
            "open_booking": _booking_summary(open_order) if open_order else None,
        })
    return JsonResponse({"success": True, "categories": categories})


def _resolve_customer(data):
    """
    The selected customer, an existing user with the typed phone number, or a
    new CUSTOMER. Returns (user, created) or raises ValueError(message).
    """
    if data.get("customer_id"):
        customer_id = _parse_uuid(data["customer_id"])
        user = User.objects.filter(pk=customer_id).first() if customer_id else None
        if user is None:
            raise ValueError("The selected customer no longer exists. Search again.")
        return user, False

    phone = normalize_phone(data.get("phone"))
    if not phone:
        raise ValueError("Enter a valid 10-digit mobile number.")
    user = find_user_by_phone(phone)
    if user:
        return user, False
    return User.objects.create_user(phone_number=phone, role=User.Role.CUSTOMER), True


@require_POST
@never_cache
def quick_book_create(request):
    """Create (and broadcast) an instant booking for a caller."""
    if not is_agent(request.user):
        return _forbidden()
    try:
        data = json.loads(request.body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return _error("Invalid request.")

    category = Category.objects.filter(
        pk=data.get("category_id") if str(data.get("category_id", "")).isdecimal() else None,
        is_active=True, instant_enabled=True,
    ).first()
    if category is None:
        return _error("Select a category that accepts instant bookings.")

    coords = _parse_coords(data.get("lat"), data.get("lng"))
    if coords is None:
        return _error("Pin the job location on the map.")
    address = (data.get("address") or "").strip()
    if not address:
        return _error("Service address is required.")

    try:
        quantity = int(data.get("quantity"))
    except (TypeError, ValueError):
        quantity = 0
    if not 1 <= quantity <= MAX_QUANTITY:
        return _error("Quantity must be a whole number of at least 1.")

    scheduled_date = timezone.localdate()
    if data.get("scheduled_date"):
        try:
            scheduled_date = date.fromisoformat(str(data["scheduled_date"]))
        except ValueError:
            return _error("Enter a valid work date.")
        if scheduled_date < timezone.localdate():
            return _error("Work date cannot be in the past.")

    unit_price = None
    if str(data.get("unit_price") if data.get("unit_price") is not None else "").strip():
        try:
            unit_price = Decimal(str(data["unit_price"]))
        except InvalidOperation:
            return _error("Enter a valid unit price.")
        if not unit_price.is_finite() or unit_price >= MAX_UNIT_PRICE:
            return _error("Enter a valid unit price.")

    name = (data.get("name") or "").strip()[:255]
    note = (data.get("note") or "").strip()

    try:
        with transaction.atomic():
            customer, created = _resolve_customer(data)
            if not customer.is_active:
                raise ValueError("This account is deactivated. Reactivate it from Users first.")

            open_order = active_instant_booking(customer, category)
            if open_order:
                return _error(
                    f"This customer already has an open {category.name} order ({open_order.booking_id}).",
                    status=409, booking=_booking_summary(open_order),
                )

            if name and customer.role == User.Role.CUSTOMER:
                profile, _ = CustomerProfile.objects.get_or_create(user=customer)
                if created or not profile.full_name:
                    profile.full_name = name
                    profile.save(update_fields=["full_name"])

            # A new caller's first job spot becomes their saved address; an
            # existing customer's is only replaced when the agent asks.
            if created or data.get("save_location"):
                UserLocation.objects.update_or_create(
                    user=customer,
                    defaults={"address": address, "latitude": coords[0], "longitude": coords[1]},
                )

            booking, providers_notified = create_instant_booking(
                customer=customer,
                category=category,
                lat=coords[0],
                lng=coords[1],
                address=address,
                quantity=quantity,
                note=note,
                scheduled_date=scheduled_date,
                unit_price_override=unit_price,
                created_by_agent=request.user,
            )
    except (ValueError, InstantBookingError) as exc:
        return _error(str(exc))

    return JsonResponse({
        "success": True,
        "booking_id": booking.booking_id,
        "order_number": booking.order_number,
        "total_amount": str(booking.total_amount),
        "providers_notified": providers_notified,
        "customer_created": created,
        "detail_url": reverse("adminpanel:booking-detail", kwargs={"booking_id": booking.booking_id}),
    })
