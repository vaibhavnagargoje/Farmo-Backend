"""Instant booking creation and provider broadcast.

Shared by the customer API (InstantBookingCreateSerializer) and the admin
panel's Quick Book, so an order placed by phone reaches the same providers at
the same price as one placed in the app.
"""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import ACos, Cos, Radians, Sin
from django.utils import timezone

from services.models import Service

from .models import Booking, InstantBookingRequest

ACTIVE_INSTANT_STATUSES = (Booking.Status.SEARCHING, Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS)
CENTS = Decimal("0.01")


class InstantBookingError(Exception):
    """The booking cannot be placed as requested; the message is user-facing."""


def find_nearby_services(category, lat, lng, radius_km):
    """
    Active, available services of verified partners within *radius_km*,
    annotated with ``distance`` (km, Haversine on the partner's UserLocation)
    and ordered nearest first. Partners busy today are excluded.
    """
    from availability.models import BusyDay
    today = timezone.now().date()

    busy_partner_ids = BusyDay.objects.filter(
        date=today,
        service__isnull=True,  # Partner-level busy
    ).values_list('partner_id', flat=True)

    queryset = Service.objects.filter(
        category=category,
        status=Service.Status.ACTIVE,
        is_available=True,
        partner__is_available=True,  # Master switch
        partner__is_verified=True,
    ).exclude(
        partner__user__location__isnull=True
    ).exclude(
        partner__user__location__latitude__isnull=True
    ).exclude(
        partner__user__location__longitude__isnull=True
    ).exclude(
        partner_id__in=busy_partner_ids  # Calendar availability check
    )

    lat_value = Value(float(lat), output_field=FloatField())
    lng_value = Value(float(lng), output_field=FloatField())
    return queryset.annotate(
        distance=ExpressionWrapper(
            Value(6371.0) * ACos(
                Cos(Radians(lat_value)) *
                Cos(Radians(F('partner__user__location__latitude'))) *
                Cos(Radians(F('partner__user__location__longitude')) - Radians(lng_value)) +
                Sin(Radians(lat_value)) *
                Sin(Radians(F('partner__user__location__latitude')))
            ),
            output_field=FloatField()
        )
    ).filter(distance__lte=radius_km).order_by('distance')


def count_nearby_partners(category, lat, lng):
    """How many providers a new instant booking at this spot would notify."""
    return (
        find_nearby_services(category, lat, lng, category.instant_search_radius_km)
        .values('partner_id').distinct().count()
    )


def active_instant_booking(customer, category):
    """The customer's open instant booking in this category, if any (one at a time)."""
    return Booking.objects.filter(
        customer=customer,
        booking_type=Booking.BookingType.INSTANT,
        category_id=getattr(category, 'pk', category),
        status__in=ACTIVE_INSTANT_STATUSES,
    ).first()


def _broadcast(booking, broadcast_round):
    """Create one request per nearby partner; the post_save signal sends the push."""
    category = booking.category
    nearby = find_nearby_services(category, booking.lat, booking.lng, category.instant_search_radius_km)
    seen = set()
    for service in nearby.select_related('partner'):
        if service.partner_id in seen:
            continue
        seen.add(service.partner_id)
        InstantBookingRequest.objects.create(
            booking=booking,
            provider=service.partner,
            broadcast_round=broadcast_round,
            distance_km=round(service.distance, 2) if service.distance else None,
            response_deadline=booking.expires_at,
        )
    return len(seen)


def create_instant_booking(*, customer, category, lat, lng, address, quantity, note='',
                           scheduled_date=None, scheduled_time=None,
                           unit_price_override=None, created_by_agent=None):
    """
    Price the job for its location, create a SEARCHING instant booking and
    notify nearby providers. Returns ``(booking, providers_notified)``.

    ``unit_price_override`` lets an agent agree a different price on a call;
    the system price is then kept in ``original_unit_price``.
    """
    from locations.pricing import resolve_instant_price

    system_price, price_unit, _zone = resolve_instant_price(category, lat, lng)
    if system_price <= 0:
        raise InstantBookingError("Instant booking price is not configured for this category.")
    unit_price = Decimal(str(system_price)).quantize(CENTS)
    original_unit_price = None
    if unit_price_override is not None:
        override = Decimal(str(unit_price_override)).quantize(CENTS)
        if override <= 0:
            raise InstantBookingError("Unit price must be greater than zero.")
        if override != unit_price:
            original_unit_price, unit_price = unit_price, override

    now = timezone.localtime(timezone.now())
    with transaction.atomic():
        booking = Booking.objects.create(
            booking_type=Booking.BookingType.INSTANT,
            customer=customer,
            category=category,
            status=Booking.Status.SEARCHING,
            address=address,
            lat=lat,
            lng=lng,
            quantity=quantity,
            price_unit=price_unit,
            unit_price=unit_price,
            original_unit_price=original_unit_price,
            total_amount=(unit_price * quantity).quantize(CENTS),
            note=note,
            scheduled_date=scheduled_date or now.date(),
            scheduled_time=scheduled_time or now.time().replace(second=0, microsecond=0),
            created_by_agent=created_by_agent,
        )
        providers_notified = _broadcast(booking, broadcast_round=1)
        booking.broadcast_count = 1
        booking.current_broadcast_radius = category.instant_search_radius_km
        booking.save(update_fields=['broadcast_count', 'current_broadcast_radius'])
    return booking, providers_notified


def rebroadcast_instant_booking(booking):
    """
    Search again for an instant booking nobody accepted: reopen it with a
    fresh timeout and notify nearby providers in a new broadcast round.
    Returns ``(booking, providers_notified)``.
    """
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking.pk)
        if booking.booking_type != Booking.BookingType.INSTANT or booking.status not in (
            Booking.Status.SEARCHING, Booking.Status.EXPIRED,
        ):
            raise InstantBookingError("Only unassigned instant orders can be searched again.")
        if booking.category is None:
            raise InstantBookingError("This order has no category.")
        if booking.lat is None or booking.lng is None:
            raise InstantBookingError("This order has no map location.")

        now = timezone.now()
        booking.instant_requests.filter(
            status=InstantBookingRequest.RequestStatus.PENDING,
        ).update(status=InstantBookingRequest.RequestStatus.EXPIRED, responded_at=now)
        booking.status = Booking.Status.SEARCHING
        booking.expires_at = now + timedelta(minutes=booking.category.instant_timeout_minutes)
        booking.broadcast_count += 1
        booking.current_broadcast_radius = booking.category.instant_search_radius_km
        booking.save(update_fields=[
            'status', 'expires_at', 'broadcast_count', 'current_broadcast_radius', 'updated_at',
        ])
        providers_notified = _broadcast(booking, broadcast_round=booking.broadcast_count)
    return booking, providers_notified
