"""Booking figures for the Bookings overview and the Dashboard."""

import math
from datetime import date, timedelta
from urllib.parse import urlencode

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
from django.utils import timezone

from bookings.models import Booking, ProviderContact

PERIODS = [("today", "Today"), ("7d", "7 days"), ("30d", "30 days"), ("month", "This month"), ("custom", "Custom")]
MAX_RANGE_DAYS = 366


def resolve_period(params, today=None):
    """``(key, start, end)`` with inclusive dates from ?period=&from=&to= (default: 30 days)."""
    today = today or timezone.localdate()
    key = params.get("period") or "30d"
    if key == "today":
        return key, today, today
    if key == "7d":
        return key, today - timedelta(days=6), today
    if key == "month":
        return key, today.replace(day=1), today
    if key == "custom":
        try:
            start, end = date.fromisoformat(params.get("from", "")), date.fromisoformat(params.get("to", ""))
        except ValueError:
            pass
        else:
            start, end = min(start, end), max(start, end)
            return key, max(start, end - timedelta(days=MAX_RANGE_DAYS - 1)), end
    return "30d", today - timedelta(days=29), today


def previous_period(start, end):
    """The equally long period just before ``start``."""
    length = (end - start).days + 1
    return start - timedelta(days=length), start - timedelta(days=1)


def needs_attention_q(now=None):
    """Orders whose provider search ran out while the job is still upcoming."""
    now = now or timezone.now()
    return Q(
        provider__isnull=True,
        scheduled_date__gte=timezone.localdate(),
    ) & (
        Q(status=Booking.Status.EXPIRED)
        | Q(status=Booking.Status.SEARCHING, expires_at__lt=now)
    )


def live_counts():
    """Right-now counts, independent of any period (tiles link to filtered lists)."""
    now = timezone.now()
    counts = Booking.objects.aggregate(
        new_today=Count("id", filter=Q(created_at__date=timezone.localdate())),
        searching=Count("id", filter=Q(status=Booking.Status.SEARCHING) & (Q(expires_at__isnull=True) | Q(expires_at__gte=now))),
        active=Count("id", filter=Q(status__in=(Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS))),
        needs_attention=Count("id", filter=needs_attention_q(now)),
    )
    counts["contacts_today"] = ProviderContact.objects.filter(created_at__date=timezone.localdate()).count()
    return counts


ACTIVE_FILTER = "ACTIVE"  # list pseudo-status: confirmed or in progress


def live_tiles():
    """``live_counts`` as linkable tiles (Bookings overview and Dashboard)."""
    live = live_counts()
    orders = reverse("adminpanel:bookings-list")
    today = timezone.localdate().isoformat()
    return [
        {"label": "New today", "value": live["new_today"], "hint": "created today",
         "url": orders + "?" + urlencode({"date_field": "created", "from": today, "to": today})},
        {"label": "Searching", "value": live["searching"], "hint": "waiting for a provider",
         "url": orders + "?" + urlencode({"status": Booking.Status.SEARCHING})},
        {"label": "Needs attention", "value": live["needs_attention"], "hint": "search ran out, job upcoming",
         "url": orders + "?attention=1", "alert": True},
        {"label": "Active", "value": live["active"], "hint": "assigned or in progress",
         "url": orders + "?" + urlencode({"status": ACTIVE_FILTER})},
        {"label": "Direct contacts", "value": live["contacts_today"], "hint": "farmers who called a provider today",
         "url": reverse("adminpanel:provider-contacts") + "?" + urlencode({"from": today, "to": today})},
    ]


def _period_qs(start, end):
    return Booking.objects.filter(created_at__date__gte=start, created_at__date__lte=end)


def period_stats(start, end):
    stats = _period_qs(start, end).aggregate(
        total=Count("id"),
        completed=Count("id", filter=Q(status=Booking.Status.COMPLETED)),
        cancelled=Count("id", filter=Q(status=Booking.Status.CANCELLED)),
        assigned=Count("id", filter=Q(provider__isnull=False)),
        by_phone=Count("id", filter=Q(created_by_agent__isnull=False)),
        gmv=Sum("total_amount", filter=Q(status=Booking.Status.COMPLETED)),
        avg_assign=Avg(
            ExpressionWrapper(F("assigned_at") - F("created_at"), output_field=DurationField()),
            filter=Q(assigned_at__isnull=False),
        ),
    )
    total = stats["total"]
    stats["gmv"] = stats["gmv"] or 0
    stats["fulfilment_rate"] = round(100 * stats["assigned"] / total, 1) if total else None
    stats["cancellation_rate"] = round(100 * stats["cancelled"] / total, 1) if total else None
    avg = stats.pop("avg_assign")
    stats["avg_assign_minutes"] = round(avg.total_seconds() / 60, 1) if avg is not None else None
    return stats


def kpis(start, end):
    """Period KPIs with the change against the previous period of the same length."""
    current = period_stats(start, end)
    previous = period_stats(*previous_period(start, end))

    def tile(key, label, fmt, delta_fmt=None, higher_is_better=True):
        value, before = current[key], previous[key]
        delta = None
        if value is not None and before is not None:
            delta = round(float(value) - float(before), 1)
        return {
            "label": label,
            "value": fmt(value) if value is not None else "—",
            "delta": delta,
            "delta_display": (delta_fmt or fmt)(abs(delta)) if delta else "",
            "good": None if not delta else (delta > 0) == higher_is_better,
        }

    count = lambda v: f"{int(v):,}"
    percent = lambda v: f"{v:g}%"
    points = lambda v: f"{v:g} pts"
    rupees = lambda v: f"₹{float(v):,.0f}"
    minutes = lambda v: f"{v:g} min"
    return current, [
        tile("total", "Bookings", count),
        tile("completed", "Completed", count),
        tile("fulfilment_rate", "Fulfilment", percent, points),
        tile("cancellation_rate", "Cancellation rate", percent, points, higher_is_better=False),
        tile("gmv", "Completed value", rupees),
        tile("avg_assign_minutes", "Avg. time to assign", minutes, higher_is_better=False),
    ]


def _nice_ticks(peak, count=4):
    """Clean y-axis ticks (0, 5, 10, ...) covering ``peak`` bookings."""
    if peak <= count:
        return list(range(0, max(peak, 1) + 1))
    raw = peak / count
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(int(m * magnitude) for m in (1, 2, 5, 10) if m * magnitude >= raw)
    return list(range(0, step * math.ceil(peak / step) + 1, step))


def trend_series(start, end, max_labels=8):
    """
    Bookings per created day (per week for ranges over 62 days), split by
    source (placed in the app or by an agent on a phone call), with empty
    buckets kept so gaps show. Includes y-axis ticks.
    """
    weekly = (end - start).days + 1 > 62
    rows = (
        _period_qs(start, end)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(n=Count("id"), phone=Count("id", filter=Q(created_by_agent__isnull=False)))
    )
    by_day = {row["day"]: {"app": row["n"] - row["phone"], "phone": row["phone"]} for row in rows}

    buckets = []
    day = start - timedelta(days=start.weekday()) if weekly else start
    while day <= end:
        last = min(day + timedelta(days=6 if weekly else 0), end)
        first = max(day, start)
        app = phone = 0
        d = first
        while d <= last:
            counts = by_day.get(d, {})
            app += counts.get("app", 0)
            phone += counts.get("phone", 0)
            d += timedelta(days=1)
        buckets.append({
            "label": ("Week of " if weekly else "") + first.strftime("%d %b"),
            "short_label": first.strftime("%d %b"),
            "from": first.isoformat(), "to": last.isoformat(),
            "app": app, "phone": phone, "total": app + phone,
        })
        day = last + timedelta(days=1)

    ticks = _nice_ticks(max((b["total"] for b in buckets), default=0))
    top = ticks[-1]
    label_every = math.ceil(len(buckets) / max_labels)
    for index, bucket in enumerate(buckets):
        bucket["height"] = round(100 * bucket["total"] / top, 2)
        bucket["show_label"] = index % label_every == 0
    return {
        "weekly": weekly,
        "buckets": buckets,
        "ticks": [{"value": t, "bottom": round(100 * t / top, 2)} for t in reversed(ticks)],
        "has_data": any(b["total"] for b in buckets),
    }


def status_breakdown(start, end):
    counts = dict(_period_qs(start, end).values_list("status").annotate(n=Count("id")))
    return _with_widths([
        {"status": value, "label": label, "count": counts.get(value, 0)}
        for value, label in Booking.Status.choices if counts.get(value)
    ])


def category_breakdown(start, end, limit=8):
    rows = (
        _period_qs(start, end)
        .values("category_id", "category__name")
        .annotate(n=Count("id"))
        .order_by("-n", "category__name")[:limit]
    )
    return _with_widths([
        {"category_id": row["category_id"], "label": row["category__name"] or "No category", "count": row["n"]}
        for row in rows
    ])


def _with_widths(rows):
    """Bar length (% of the largest) for horizontal bar lists."""
    peak = max((row["count"] for row in rows), default=0)
    for row in rows:
        row["width"] = round(100 * row["count"] / peak, 2) if peak else 0
    return rows
