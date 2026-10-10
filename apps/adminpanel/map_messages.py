"""Allowlisted Marathi dispatch drafts; opening a draft never sends a message."""

import json
import re
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from django.conf import settings

from .map_data import ASSIGNED_STATUSES, distance_km, user_name


def coarse_area_label(lat, lng):
    """Resolve only town/district components, never a formatted street address.

    This optional lookup runs on an explicit draft action, has a short timeout,
    and stores no geocoding response. Restricted/unconfigured keys fail closed.
    """
    if lat is None or lng is None:
        return ""
    key = getattr(settings, "GOOGLE_GEOCODING_API_KEY", "") or getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if not key:
        return ""
    query = urlencode({"latlng": f"{lat},{lng}", "language": "mr", "key": key})
    try:
        with urlopen(f"https://maps.googleapis.com/maps/api/geocode/json?{query}", timeout=3) as response:
            data = json.loads(response.read(256000).decode("utf-8"))
        if data.get("status") != "OK":
            return ""
        parts = {}
        allowed = ("locality", "administrative_area_level_3", "administrative_area_level_2", "administrative_area_level_1")
        for result in data.get("results", []):
            for component in result.get("address_components", []):
                name = " ".join(str(component.get("long_name", "")).split())[:80]
                if not name:
                    continue
                for kind in allowed:
                    if kind in component.get("types", []):
                        parts.setdefault(kind, name)
        local = parts.get("locality") or parts.get("administrative_area_level_3")
        district = parts.get("administrative_area_level_2") or parts.get("administrative_area_level_1")
        return ", ".join(dict.fromkeys(part for part in (local, district) if part))
    except (URLError, OSError, ValueError, TypeError, AttributeError):
        return ""


def normalized_phone(value):
    raw = str(value or "").strip()
    if not re.fullmatch(r"[+()\s0-9.-]+", raw):
        return ""
    digits = re.sub(r"[^0-9]", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10 and not raw.startswith("+"):
        digits = "91" + digits
    return digits if 8 <= len(digits) <= 15 and not digits.startswith("0") else ""


def build_message(booking, partner, area_label=""):
    """The recipient relation AND accepted state determine disclosure."""
    full = booking.provider_id == partner.id and booking.status in ASSIGNED_STATUSES
    category = booking.category or (booking.service.category if booking.service_id else None)
    work = category.get_name("mr") if category else "शेतीचे काम"
    unit_names = {"HOUR": "तास", "ACRE": "एकर", "DAY": "दिवस", "KM": "किमी", "PUMP": "पंप", "TRIP": "फेरी"}
    unit = unit_names.get(str(booking.price_unit).upper(), booking.price_unit)
    loc = getattr(partner.user, "location", None)
    dist = distance_km(booking.lat, booking.lng, loc.latitude if loc else None, loc.longitude if loc else None)
    lines = ["नमस्कार! फार्मोकडून कामाची माहिती:", f"ऑर्डर: {booking.order_number or booking.booking_id}", f"काम: {work}", f"कामाचे प्रमाण: {booking.quantity_display} {unit}"]
    if booking.scheduled_date:
        date = booking.scheduled_date.strftime("%d-%m-%Y")
        time = booking.scheduled_time.strftime("%H:%M") if booking.scheduled_time else ""
        lines.append(f"दिनांक / वेळ: {date}{' · ' + time if time else ''}")
    lines.append(f"परिसर: {area_label or 'गाव / परिसराची माहिती उपलब्ध नाही'}")
    lines.append(f"तुमच्या नोंदवलेल्या ठिकाणापासून अंदाजे अंतर: {dist:.1f} किमी (सरळ रेषेतील)" if dist is not None else "अंदाजे अंतर: उपलब्ध नाही")
    if full:
        lines.extend([f"शेतकऱ्याचे नाव: {user_name(booking.customer)}", f"फोन: {booking.customer.phone_number}", f"कामाचा पत्ता: {booking.address}"])
        if booking.lat is not None and booking.lng is not None:
            lines.append(f"नकाशा: https://www.google.com/maps/search/?api=1&query={booking.lat},{booking.lng}")
        if booking.service_id:
            lines.append(f"सेवा: {booking.service.title}")
        discount = f" · सूट: ₹{booking.discount_amount}" if booking.discount_amount else ""
        lines.append(f"ठरलेला दर: ₹{booking.unit_price} / {unit}{discount} · एकूण: ₹{booking.total_amount}")
        if booking.note:
            lines.append(f"कामाबद्दल सूचना: {booking.note}")
        lines.append("हे काम तुम्हाला नियुक्त केले आहे. कृपया शेतकऱ्याशी संपर्क साधा.")
    elif booking.status in ASSIGNED_STATUSES:
        lines.append("या ऑर्डरसाठी प्रदाता आधीच नियुक्त आहे. ही केवळ चौकशी आहे; काम उपलब्ध असल्याची खात्री फार्मोकडून घ्या.")
    else:
        lines.append("या कामासाठी तुम्ही उपलब्ध आहात का? कृपया फार्मोला कळवा. नियुक्तीनंतर शेतकऱ्याचे संपर्क तपशील मिळतील.")
    return "\n".join(lines), "full" if full else "limited", round(dist, 2) if dist is not None else None
