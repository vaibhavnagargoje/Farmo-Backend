"""
Location-aware price resolver for instant bookings.

Usage:
    from locations.pricing import resolve_instant_price

    price, unit, zone_name = resolve_instant_price(category, user_lat, user_lng)
"""

import math
from decimal import Decimal


def _haversine_km(lat1, lng1, lat2, lng2):
    """Return the great-circle distance in km between two points."""
    R = 6371.0  # Earth radius in km
    lat1, lng1, lat2, lng2 = map(math.radians, [
        float(lat1), float(lng1), float(lat2), float(lng2),
    ])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_instant_price(category, user_lat, user_lng):
    """
    Resolve the instant-booking price for *category* at the customer's location.

    Resolution order
    ────────────────
    1. Find all **active, geographic** zones for this category
       (zones that have center_lat/center_lng set).
    2. Compute Haversine distance from the customer to each zone center.
    3. Keep only zones whose radius covers the customer.
    4. Pick the **closest** zone → use its price.
    5. If no geographic zone matches → use the **default zone**
       (the one with ``is_default=True``).
    6. If there is no default zone either → fall back to
       ``category.instant_price`` / ``category.instant_price_unit``
       (full backward compatibility).

    Returns
    -------
    tuple[float, str, str | None]
        ``(unit_price, price_unit, zone_name)``
        ``zone_name`` is ``None`` when the global fallback is used.
    """
    from locations.pricing_models import PricingZone  # avoid circular import

    zones = PricingZone.objects.filter(category=category, is_active=True)

    if not zones.exists():
        # No zones configured at all → global fallback
        return (
            round(float(category.instant_price), 2),
            category.instant_price_unit,
            None,
        )

    # ── Step 1-4: geographic zones ──
    best_zone = None
    best_distance = float('inf')

    default_zone = None

    for zone in zones:
        if zone.is_default:
            default_zone = zone
            continue  # don't treat default as a geographic zone

        if zone.center_lat is None or zone.center_lng is None:
            continue  # skip zones without coordinates

        dist = _haversine_km(user_lat, user_lng, zone.center_lat, zone.center_lng)

        if dist <= zone.radius_km and dist < best_distance:
            best_zone = zone
            best_distance = dist

    # ── Step 5: return best match or fallback ──
    if best_zone:
        return (
            round(float(best_zone.price), 2),
            best_zone.price_unit,
            best_zone.name,
        )

    if default_zone:
        return (
            round(float(default_zone.price), 2),
            default_zone.price_unit,
            default_zone.name,
        )

    # ── Step 6: global fallback ──
    return (
        round(float(category.instant_price), 2),
        category.instant_price_unit,
        None,
    )
