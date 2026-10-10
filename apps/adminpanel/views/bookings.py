"""Bookings section pages: overview analytics, order lists, detail, export,
and the list of direct provider contacts.

Quick Book endpoints live in quick_book.py; state changes on a booking
(assign, cancel, complete, retry search) live in booking_actions.py.
"""

import csv
import re
from datetime import date
from urllib.parse import urlencode

from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from bookings.models import Booking, BookingOffer, ProviderContact
from services.models import Category, Service, ServicePriceUnit

from .. import booking_analytics as analytics
from .booking_actions import pricing_locked_reason
from ..map_data import candidate_data, partner_data, partner_queryset, user_name
from ..permissions import is_agent

LOGIN_URL = "/api/v1/admin/login/"
PAGE_SIZE = 25
FILTER_KEYS = ("q", "status", "category", "source", "attention", "date_field", "from", "to")
ACTIVE_FILTER = analytics.ACTIVE_FILTER

CONTACT_FILTER_KEYS = ("q", "outcome", "category", "from", "to")


def _query(params):
    """Query string (with leading ?) for the non-empty params."""
    clean = {key: value for key, value in params.items() if value not in ("", None)}
    return "?" + urlencode(clean) if clean else ""


def _parse_date(value):
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


# ── Overview ───────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url=LOGIN_URL)
@require_GET
def bookings_overview(request):
    period, start, end = analytics.resolve_period(request.GET)
    current, kpis = analytics.kpis(start, end)
    list_url = reverse("adminpanel:bookings-list")
    created_range = {"date_field": "created", "from": start.isoformat(), "to": end.isoformat()}
    statuses = analytics.status_breakdown(start, end)
    for row in statuses:
        row["url"] = list_url + _query({**created_range, "status": row["status"]})
    categories = analytics.category_breakdown(start, end)
    for row in categories:
        row["url"] = list_url + _query({**created_range, "category": row["category_id"] or ""})

    return render(request, "adminpanel/bookings_overview.html", {
        "page_title": "Bookings",
        "periods": analytics.PERIODS,
        "period": period,
        "start": start,
        "end": end,
        "kpis": kpis,
        "stats": current,
        "live_tiles": analytics.live_tiles(),
        "trend": analytics.trend_series(start, end),
        "statuses": statuses,
        "categories": categories,
        "period_list_url": list_url + _query(created_range),
        "recent_bookings": Booking.objects.select_related(
            "customer__customer_profile", "category",
        ).order_by("-created_at")[:10],
    })


# ── Lists ──────────────────────────────────────────────────────────────────

def filtered_bookings(params):
    """Bookings matching the list filters, newest first, plus the cleaned filter values."""
    filters = {key: (params.get(key) or "").strip() for key in FILTER_KEYS}
    qs = Booking.objects.select_related(
        "customer__customer_profile", "category", "provider__user", "service", "created_by_agent",
    )

    q = filters["q"]
    if q:
        condition = (
            Q(booking_id__icontains=q) | Q(order_number__icontains=q)
            | Q(customer__customer_profile__full_name__icontains=q)
            | Q(provider__business_name__icontains=q) | Q(address__icontains=q)
        )
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 3:
            condition |= Q(customer__phone_number__contains=digits[-10:]) | Q(provider__user__phone_number__contains=digits[-10:])
        qs = qs.filter(condition)

    if filters["status"] in Booking.Status.values:
        qs = qs.filter(status=filters["status"])
    elif filters["status"] == ACTIVE_FILTER:
        qs = qs.filter(status__in=(Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS))
    else:
        filters["status"] = ""
    if filters["category"].isdecimal():
        qs = qs.filter(category_id=filters["category"])
    else:
        filters["category"] = ""
    if filters["source"] == "phone":
        qs = qs.filter(created_by_agent__isnull=False)
    elif filters["source"] == "app":
        qs = qs.filter(created_by_agent__isnull=True)
    else:
        filters["source"] = ""
    if filters["attention"] == "1":
        qs = qs.filter(analytics.needs_attention_q())
    else:
        filters["attention"] = ""

    if filters["date_field"] != "scheduled":
        filters["date_field"] = "created" if (filters["from"] or filters["to"]) else ""
    field = "scheduled_date" if filters["date_field"] == "scheduled" else "created_at__date"
    for key, lookup in (("from", "gte"), ("to", "lte")):
        day = _parse_date(filters[key])
        if day:
            qs = qs.filter(**{f"{field}__{lookup}": day})
        else:
            filters[key] = ""
    return qs.order_by("-created_at"), filters


def _filter_chips(filters, base_url):
    """Removable chips describing the active filters."""
    labels = {**dict(Booking.Status.choices), ACTIVE_FILTER: "Active (assigned or in progress)"}
    chips = []

    def chip(text, *keys):
        rest = {k: v for k, v in filters.items() if k not in keys}
        chips.append({"label": text, "remove_url": base_url + _query(rest)})

    if filters["q"]:
        chip(f'Search: "{filters["q"]}"', "q")
    if filters["status"]:
        chip(labels[filters["status"]], "status")
    if filters["category"]:
        name = Category.objects.filter(pk=filters["category"]).values_list("name", flat=True).first()
        chip(name or "Category", "category")
    if filters["source"]:
        chip("Phone (Quick Book)" if filters["source"] == "phone" else "App", "source")
    if filters["attention"]:
        chip("Needs attention", "attention")
    if filters["from"] or filters["to"]:
        what = "Work date" if filters["date_field"] == "scheduled" else "Created"
        span = f'{filters["from"] or "…"} → {filters["to"] or "…"}'
        chip(f"{what}: {span}", "from", "to", "date_field")
    return chips


@user_passes_test(is_agent, login_url=LOGIN_URL)
@require_GET
def bookings_list(request):
    heading = "All orders"
    base_url = reverse("adminpanel:bookings-list")
    qs, filters = filtered_bookings(request.GET)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    query = _query(filters)
    return render(request, "adminpanel/bookings_list.html", {
        "page_title": heading,
        "heading": heading,
        "page_obj": page_obj,
        "filters": filters,
        "chips": _filter_chips(filters, base_url),
        "base_url": base_url,
        "page_prefix": (query + "&" if query else "?") + "page=",
        "export_url": reverse("adminpanel:bookings-export") + query,
        "status_choices": [*Booking.Status.choices, (ACTIVE_FILTER, "Active (assigned or in progress)")],
        "categories": Category.objects.order_by("name"),
        "advanced_count": sum(bool(filters[k]) for k in ("status", "category", "source", "from", "to")),
    })


# ── Export ─────────────────────────────────────────────────────────────────

class _Echo:
    def write(self, value):
        return value


def _cell(value):
    """CSV-safe cell: neutralise text that spreadsheet apps would run as a formula."""
    if value is None:
        return ""
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


EXPORT_COLUMNS = [
    "Booking ID", "Order number", "Status", "Source", "Created by agent",
    "Customer name", "Customer phone", "Category", "Service", "Provider", "Provider phone",
    "Quantity", "Unit", "Unit price", "Original unit price", "Subtotal", "Discount", "Total amount", "Payment status",
    "Address", "Latitude", "Longitude", "Work date", "Work time",
    "Created at", "Assigned at", "Started at", "Completed at", "Cancellation reason", "Note",
]


def _export_row(b):
    local = lambda dt: timezone.localtime(dt).strftime("%Y-%m-%d %H:%M") if dt else ""
    provider = b.provider
    return [
        b.booking_id, b.order_number, b.get_status_display(),
        "Phone" if b.created_by_agent_id else "App",
        b.created_by_agent.phone_number if b.created_by_agent_id else "",
        user_name(b.customer), b.customer.phone_number,
        b.category.name if b.category else "", b.service.title if b.service else "",
        provider.business_name if provider else "", provider.user.phone_number if provider else "",
        b.quantity_display, b.price_unit, b.unit_price, b.original_unit_price, b.subtotal, b.discount_amount,
        b.total_amount, b.get_payment_status_display(),
        b.address, b.lat, b.lng,
        b.scheduled_date.isoformat() if b.scheduled_date else "",
        b.scheduled_time.strftime("%H:%M") if b.scheduled_time else "",
        local(b.created_at), local(b.assigned_at), local(b.work_started_at), local(b.work_completed_at),
        b.cancellation_reason, b.note,
    ]


@user_passes_test(is_agent, login_url=LOGIN_URL)
@require_GET
def bookings_export(request):
    qs, _filters = filtered_bookings(request.GET)
    writer = csv.writer(_Echo())

    def rows():
        yield "﻿"  # BOM so Excel opens UTF-8 (₹, Marathi names) correctly
        yield writer.writerow(EXPORT_COLUMNS)
        for booking in qs.iterator(chunk_size=500):
            yield writer.writerow([_cell(value) for value in _export_row(booking)])

    filename = f"farmo-bookings-{timezone.localdate():%Y%m%d}.csv"
    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ── Detail ─────────────────────────────────────────────────────────────────

def _assignment_candidates(booking):
    """Partners offering the booking's category, eligible ones first, nearest first."""
    category_id = booking.category_id or (booking.service.category_id if booking.service_id else None)
    if not category_id:
        return [], []
    dates = {booking.scheduled_date or timezone.localdate(), timezone.localdate()}
    partners = partner_queryset(dates).filter(
        services__category_id=category_id, services__status=Service.Status.ACTIVE,
    ).distinct()
    eligible, other = [], []
    for partner in partners:
        pdata = partner_data(partner)
        candidate = candidate_data(booking, pdata)
        row = {**candidate, "name": pdata["name"], "phone": pdata["phone"], "profile_url": pdata["profile_url"]}
        (eligible if candidate["is_eligible"] else other).append(row)
    by_distance = lambda row: (row["distance_km"] is None, row["distance_km"] or 0)
    return sorted(eligible, key=by_distance)[:15], sorted(other, key=by_distance)[:15]


@user_passes_test(is_agent, login_url=LOGIN_URL)
@require_GET
def booking_detail(request, booking_id):
    booking = Booking.objects.select_related(
        "customer__customer_profile", "customer__location", "category", "service__price_unit",
        "provider__user", "created_by_agent", "accepted_by_agent", "cancelled_by", "price_updated_by",
    ).filter(booking_id=booking_id).first()
    if booking is None:
        raise Http404("Booking not found")

    requests = BookingOffer.objects.filter(booking=booking).select_related(
        "provider__user",
    ).order_by("-broadcast_round", "distance_km", "id")
    is_open = booking.status in (Booking.Status.SEARCHING, Booking.Status.CONFIRMED)
    can_assign = is_open and not booking.is_expired
    can_rebroadcast = booking.provider_id is None and (
        booking.status == Booking.Status.EXPIRED or (booking.status == Booking.Status.SEARCHING and booking.is_expired)
    )
    eligible, other = _assignment_candidates(booking) if can_assign else ([], [])

    timeline = [
        ("Created", booking.created_at, booking.created_by_agent and f"by agent {booking.created_by_agent.phone_number}"),
        ("Search expires" if booking.status == Booking.Status.SEARCHING else "Search ended", booking.expires_at, None),
        ("Assigned", booking.assigned_at, booking.accepted_by_agent and f"by agent {booking.accepted_by_agent.phone_number}"),
        ("Work started", booking.work_started_at, None),
        ("Completed", booking.work_completed_at, None),
        ("Price updated", booking.price_updated_at, booking.price_updated_by and f"by agent {booking.price_updated_by.phone_number}"),
    ]
    if booking.status == Booking.Status.CANCELLED:
        timeline.append(("Cancelled", booking.updated_at, booking.cancelled_by and f"by {booking.cancelled_by.phone_number}"))

    timeline.sort(key=lambda row: row[1] or booking.created_at)
    pricing_locked = pricing_locked_reason(booking)

    return render(request, "adminpanel/booking_detail.html", {
        "page_title": f"Booking {booking.booking_id}",
        "booking": booking,
        "customer_name": user_name(booking.customer),
        "unit_label": ServicePriceUnit.objects.filter(key=booking.price_unit).values_list("name", flat=True).first() or booking.price_unit,
        "requests": requests,
        "timeline": [(label, when, who) for label, when, who in timeline if when],
        "can_assign": can_assign,
        "can_reassign": booking.status == Booking.Status.CONFIRMED,
        "can_cancel": booking.status not in (Booking.Status.CANCELLED, Booking.Status.COMPLETED),
        "can_complete": booking.status in (Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS) and booking.provider_id,
        "can_rebroadcast": can_rebroadcast,
        "can_edit_pricing": pricing_locked is None,
        "pricing_locked_reason": pricing_locked,
        "eligible_partners": eligible,
        "other_partners": other,
        "maps_url": f"https://www.google.com/maps?q={booking.lat},{booking.lng}" if booking.lat is not None and booking.lng is not None else "",
    })


# ── Direct provider contacts ("Find yourself") ─────────────────────────────

def filtered_contacts(params):
    """Contacts matching the list filters, newest first, plus the cleaned filter values."""
    filters = {key: (params.get(key) or "").strip() for key in CONTACT_FILTER_KEYS}
    qs = ProviderContact.objects.select_related(
        "customer__customer_profile", "provider__user", "service", "category",
    )

    q = filters["q"]
    if q:
        condition = (
            Q(customer__customer_profile__full_name__icontains=q)
            | Q(provider__business_name__icontains=q)
            | Q(service__title__icontains=q)
            | Q(legacy_booking_id__icontains=q)
        )
        digits = re.sub(r"\D", "", q)
        if len(digits) >= 3:
            condition |= Q(customer__phone_number__contains=digits[-10:]) | Q(provider__user__phone_number__contains=digits[-10:])
        qs = qs.filter(condition)

    if filters["outcome"] not in ProviderContact.Outcome.values:
        filters["outcome"] = ""
    elif filters["outcome"]:
        qs = qs.filter(outcome=filters["outcome"])
    if filters["category"].isdecimal():
        qs = qs.filter(category_id=filters["category"])
    else:
        filters["category"] = ""
    for key, lookup in (("from", "gte"), ("to", "lte")):
        day = _parse_date(filters[key])
        if day:
            qs = qs.filter(**{f"created_at__date__{lookup}": day})
        else:
            filters[key] = ""
    return qs.order_by("-created_at"), filters


def _contact_chips(filters, base_url):
    """Removable chips describing the active contact filters."""
    chips = []

    def chip(text, *keys):
        rest = {k: v for k, v in filters.items() if k not in keys}
        chips.append({"label": text, "remove_url": base_url + _query(rest)})

    if filters["q"]:
        chip(f'Search: "{filters["q"]}"', "q")
    if filters["outcome"]:
        chip(dict(ProviderContact.Outcome.choices)[filters["outcome"]], "outcome")
    if filters["category"]:
        name = Category.objects.filter(pk=filters["category"]).values_list("name", flat=True).first()
        chip(name or "Category", "category")
    if filters["from"] or filters["to"]:
        chip(f'Called: {filters["from"] or "…"} → {filters["to"] or "…"}', "from", "to")
    return chips


@user_passes_test(is_agent, login_url=LOGIN_URL)
@require_GET
def provider_contacts_list(request):
    """Farmers who found a provider in the app and called them directly."""
    base_url = reverse("adminpanel:provider-contacts")
    qs, filters = filtered_contacts(request.GET)
    page_obj = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    query = _query(filters)
    summary = qs.aggregate(
        agreed=Count("id", filter=Q(outcome=ProviderContact.Outcome.AGREED)),
        not_agreed=Count("id", filter=Q(outcome=ProviderContact.Outcome.NOT_AGREED)),
        no_answer=Count("id", filter=Q(outcome=ProviderContact.Outcome.CALLED)),
    )
    return render(request, "adminpanel/provider_contacts_list.html", {
        "page_title": "Direct contacts",
        "page_obj": page_obj,
        "filters": filters,
        "chips": _contact_chips(filters, base_url),
        "summary": summary,
        "base_url": base_url,
        "page_prefix": (query + "&" if query else "?") + "page=",
        "outcome_choices": ProviderContact.Outcome.choices,
        "categories": Category.objects.order_by("name"),
        "advanced_count": sum(bool(filters[k]) for k in ("outcome", "category", "from", "to")),
    })
