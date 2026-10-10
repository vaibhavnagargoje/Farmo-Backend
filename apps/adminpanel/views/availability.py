"""Provider calendars, busy-day changes, and availability listing."""

import calendar
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from labor_services.models import LaborServiceType
from partners.models import PartnerProfile
from services.models import Category, Service
from users.models import CustomerProfile, User

from ..permissions import is_agent


def _availability_date(params, today):
    """Use one date for both views; tolerate old month/year links and bad input."""
    try:
        selected = date.fromisoformat(params.get("date", ""))
    except (ValueError, TypeError):
        selected = today
    try:
        year = int(params.get("year", selected.year))
        month = int(params.get("month", selected.month))
        year_offset, month_index = divmod(month - 1, 12)
        year += year_offset
        month = month_index + 1
        # Leave room for previous/next navigation at both ends.
        if not 2 <= year <= 9998:
            return today
        return date(year, month, min(selected.day, calendar.monthrange(year, month)[1]))
    except (ValueError, TypeError, OverflowError):
        return today


def _availability_url(params, **changes):
    query = {**params, **changes}
    return "?" + urlencode({key: value for key, value in query.items() if value != ""})


def _availability_calendar(selected_date, today, partner_ids, params):
    """Count the exact same partners and partner-level busy days as By day."""
    from availability.models import BusyDay
    from bookings.models import Booking

    year, month = selected_date.year, selected_date.month
    busy_counts = BusyDay.objects.filter(
        date__year=year, date__month=month,
        service__isnull=True, partner_id__in=partner_ids,
    ).values("date__day").annotate(count=Count("partner_id", distinct=True))
    busy_per_day = {row["date__day"]: row["count"] for row in busy_counts}
    # Keep the dashboard's all-bookings overview, including unassigned requests.
    booking_counts = Booking.objects.filter(
        scheduled_date__year=year, scheduled_date__month=month,
    ).exclude(status__in=[Booking.Status.CANCELLED, Booking.Status.EXPIRED]).values(
        "scheduled_date__day",
    ).annotate(count=Count("id"))
    bookings_per_day = {row["scheduled_date__day"]: row["count"] for row in booking_counts}
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        cells = []
        for day in week:
            if not day:
                cells.append(None)
                continue
            day_date = date(year, month, day)
            busy = busy_per_day.get(day, 0)
            cells.append({
                "day": day, "date": day_date,
                "free": len(partner_ids) - busy, "busy": busy,
                "bookings": bookings_per_day.get(day, 0),
                "is_past": day_date < today, "is_today": day_date == today,
                "is_selected": day_date == selected_date,
                "url": _availability_url(params, view="day", date=day_date.isoformat()),
            })
        weeks.append(cells)
    previous = selected_date.replace(day=1) - timedelta(days=1)
    following = selected_date.replace(day=calendar.monthrange(year, month)[1]) + timedelta(days=1)
    previous = previous.replace(day=min(selected_date.day, previous.day))
    following = following.replace(day=min(selected_date.day, calendar.monthrange(following.year, following.month)[1]))
    return {
        "calendar_weeks": weeks,
        "month_name": calendar.month_name[month], "year": year,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "previous_month_url": _availability_url(params, date=previous.isoformat()),
        "next_month_url": _availability_url(params, date=following.isoformat()),
    }


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def agent_worker_calendar(request, user_id):
    """
    Calendar view for a specific worker/partner.
    Shows current month by default; supports month/year navigation.
    """
    import calendar as cal_module
    from datetime import date
    from availability.models import BusyDay

    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "This user has no partner profile.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    today = date.today()
    year = int(request.GET.get("year", today.year))
    month = int(request.GET.get("month", today.month))

    # Clamp values
    if month < 1:
        month = 12
        year -= 1
    elif month > 12:
        month = 1
        year += 1

    # Build calendar data
    cal = cal_module.Calendar(firstweekday=0)  # Monday first
    month_days = cal.monthdayscalendar(year, month)

    # Get busy days for this month
    busy_days_qs = BusyDay.objects.filter(
        partner=partner_profile,
        date__year=year,
        date__month=month,
    ).select_related('booking', 'marked_by_user')

    busy_map = {}
    for bd in busy_days_qs:
        busy_map[bd.date.day] = {
            "id": bd.id,
            "marked_by": bd.get_marked_by_display(),
            "reason": bd.reason,
            "is_system": bd.marked_by == BusyDay.MarkedBy.SYSTEM,
            "booking_id": bd.booking.booking_id if bd.booking else None,
        }

    # Previous/next month
    prev_month = month - 1
    prev_year = year
    if prev_month < 1:
        prev_month = 12
        prev_year -= 1

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    month_name = cal_module.month_name[month]

    from bookings.models import Booking, BookingOffer
    pending_offers = BookingOffer.objects.filter(
        provider=partner_profile,
        status=BookingOffer.Status.PENDING,
        booking__status=Booking.Status.SEARCHING,
    ).select_related(
        'booking', 'booking__customer', 'booking__customer__customer_profile', 
        'booking__service', 'booking__category'
    ).order_by('-booking__created_at')

    active_bookings = Booking.objects.filter(
        provider=partner_profile, 
        status__in=[Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS]
    ).select_related('customer', 'customer__customer_profile', 'service', 'category').order_by('scheduled_date', '-created_at')

    context = {
        "page_title": f"Calendar — {user.phone_number}",
        "user": user,
        "partner_profile": partner_profile,
        "year": year,
        "month": month,
        "month_name": month_name,
        "month_days": month_days,
        "busy_map": busy_map,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "pending_offers": pending_offers,
"active_bookings": active_bookings,
    }
    return render(request, "adminpanel/partner_calendar.html", context)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def agent_toggle_busy_day(request, user_id):
    """
    POST: Toggle a date busy/free for a worker (used by agent from calendar UI).
    Expects: date (YYYY-MM-DD) in POST data.
    """
    from datetime import date, datetime
    from availability.models import BusyDay

    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "This user has no partner profile.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    date_str = request.POST.get("date", "")
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        messages.error(request, "Invalid date format.")
        return redirect(
            "adminpanel:worker-calendar", user_id=user_id
        )

    # Don't allow marking past dates
    if target_date < date.today():
        messages.error(request, "Cannot modify past dates.")
        return redirect(
            reverse("adminpanel:worker-calendar", kwargs={"user_id": user_id})
            + f"?year={target_date.year}&month={target_date.month}"
        )

    # Toggle
    existing = BusyDay.objects.filter(
        partner=partner_profile,
        service__isnull=True,
        date=target_date,
    ).first()

    if existing:
        if existing.marked_by == BusyDay.MarkedBy.SYSTEM:
            messages.warning(
                request,
                f"Cannot modify {target_date.strftime('%d %b')} — it's busy due to "
                f"booking {existing.booking.booking_id if existing.booking else 'unknown'}. "
                f"Cancel the booking first.",
            )
        else:
            existing.delete()
            messages.success(request, f"{target_date.strftime('%d %b %Y')} marked as FREE.")
    else:
        reason = request.POST.get("reason", "")
        BusyDay.objects.create(
            partner=partner_profile,
            service=None,
            entity_type=BusyDay.EntityType.PARTNER,
            date=target_date,
            marked_by=BusyDay.MarkedBy.AGENT,
            marked_by_user=request.user,
            reason=reason,
        )
        messages.success(request, f"{target_date.strftime('%d %b %Y')} marked as BUSY.")

    return redirect(
        reverse("adminpanel:worker-calendar", kwargs={"user_id": user_id})
        + f"?year={target_date.year}&month={target_date.month}"
    )


@require_POST
@user_passes_test(is_agent, login_url='/api/v1/admin/login/')
def agent_worker_booking_action(request, user_id):
    """
    Allow an admin to accept or decline a booking offer on behalf of the partner.
    """
    from bookings.models import Booking, BookingOffer

    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, 'This user has no partner profile.')
        return redirect('adminpanel:worker-calendar', user_id=user_id)

    req_id = request.POST.get('request_id')
    action = request.POST.get('action') # 'accept' or 'reject'

    if action not in ['accept', 'reject']:
        messages.error(request, 'Invalid action.')
        return redirect('adminpanel:worker-calendar', user_id=user_id)

    if req_id and req_id.isdecimal():
        with transaction.atomic():
            try:
                offer = BookingOffer.objects.select_for_update().get(pk=req_id, provider=partner_profile)
            except BookingOffer.DoesNotExist:
                messages.error(request, 'Request not found.')
                return redirect('adminpanel:worker-calendar', user_id=user_id)

            if offer.status != BookingOffer.Status.PENDING:
                messages.error(request, 'This request has already been responded to.')
                return redirect('adminpanel:worker-calendar', user_id=user_id)

            booking = Booking.objects.select_for_update().get(pk=offer.booking_id)

            if action == 'accept':
                if booking.status != Booking.Status.SEARCHING:
                    offer.status = BookingOffer.Status.EXPIRED
                    offer.responded_at = timezone.now()
                    offer.save(update_fields=['status', 'responded_at'])
                    messages.error(request, 'This booking is no longer available.')
                    return redirect('adminpanel:worker-calendar', user_id=user_id)

                booking.provider = partner_profile
                booking.status = Booking.Status.CONFIRMED
                booking.assigned_at = timezone.now()
                booking.accepted_by_agent = request.user
                booking.save()

                offer.status = BookingOffer.Status.ACCEPTED
                offer.responded_at = timezone.now()
                offer.save(update_fields=['status', 'responded_at'])

                # Expire others
                BookingOffer.objects.filter(
                    booking=booking, status=BookingOffer.Status.PENDING
                ).exclude(pk=req_id).update(
                    status=BookingOffer.Status.EXPIRED, responded_at=timezone.now()
                )
                messages.success(request, f'Booking {booking.booking_id} accepted on behalf of partner.')

            elif action == 'reject':
                offer.status = BookingOffer.Status.DECLINED
                offer.responded_at = timezone.now()
                offer.save(update_fields=['status', 'responded_at'])
                messages.success(request, f'Booking {booking.booking_id} declined on behalf of partner.')

    else:
        messages.error(request, 'Invalid data provided.')

    return redirect('adminpanel:worker-calendar', user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def agent_workers_by_date(request):
    """
    Availability workspace with shared filters for Calendar and By day.
    Keep the existing route so saved day links continue to work.
    """
    from availability.models import BusyDay
    from bookings.models import Booking
    from locations.pricing import _haversine_km

    today = timezone.localdate()
    selected_date = _availability_date(request.GET, today)
    view_mode = request.GET.get("view", "day" if request.GET.get("date") else "calendar")
    if view_mode not in {"calendar", "day"}:
        view_mode = "calendar"

    # Filters
    partner_type_filter = request.GET.get("type", "")
    search_q = request.GET.get("q", "").strip()
    gender_filter = request.GET.get("gender", "")
    skills_filter = request.GET.get("skills", "").strip()
    category_filter = request.GET.get("category", "")
    distance_filter = request.GET.get("distance", "")  # km radius
    sort_by = request.GET.get("sort", "")  # wage_asc, wage_desc, distance, rating
    if partner_type_filter not in PartnerProfile.PartnerType.values:
        partner_type_filter = ""
    if gender_filter not in CustomerProfile.Gender.values:
        gender_filter = ""
    if not category_filter.isdecimal() or len(category_filter) > 18:
        category_filter = ""

    # Get all active partners (is_available=True master switch)
    partners_qs = PartnerProfile.objects.filter(
        is_available=True,
    ).select_related(
        "user", "user__customer_profile", "user__location", "labor_details",
    ).prefetch_related("labor_details__service_types").order_by(
        "user__customer_profile__full_name", "user__phone_number",
    )

    if partner_type_filter:
        partners_qs = partners_qs.filter(partner_type=partner_type_filter)

    if gender_filter:
        partners_qs = partners_qs.filter(user__customer_profile__gender=gender_filter)

    if skills_filter:
        if skills_filter.isdigit():
            partners_qs = partners_qs.filter(
                partner_type=PartnerProfile.PartnerType.LABOR,
                labor_details__service_types__id=int(skills_filter),
            )
        else:
            partners_qs = partners_qs.filter(
                partner_type=PartnerProfile.PartnerType.LABOR,
            ).filter(
                Q(labor_details__service_types__name__icontains=skills_filter)
                | Q(labor_details__service_types__name_translations__icontains=skills_filter)
            ).distinct()

    if category_filter:
        partners_qs = partners_qs.filter(
            services__category_id=category_filter,
            services__status=Service.Status.ACTIVE,
        ).distinct()

    if search_q:
        partners_qs = partners_qs.filter(
            Q(user__phone_number__icontains=search_q)
            | Q(user__customer_profile__full_name__icontains=search_q)
        )

    # Get all busy partner IDs for the selected date
    busy_partner_ids = set(
        BusyDay.objects.filter(
            date=selected_date,
            service__isnull=True,
        ).values_list("partner_id", flat=True)
    )

    # Get busy day reasons for tooltip
    busy_reasons = {}
    for bd in BusyDay.objects.filter(
        date=selected_date,
        service__isnull=True,
        partner__in=partners_qs,
    ):
        busy_reasons[bd.partner_id] = {
            "reason": bd.reason,
            "marked_by": bd.get_marked_by_display(),
            "is_system": bd.marked_by == BusyDay.MarkedBy.SYSTEM,
        }

    # Agent's location (for distance calculation)
    agent_location = getattr(request.user, "location", None)
    agent_lat = float(agent_location.latitude) if agent_location and agent_location.latitude is not None else None
    agent_lng = float(agent_location.longitude) if agent_location and agent_location.longitude is not None else None
    has_agent_location = agent_lat is not None and agent_lng is not None

    # Build partner list with availability status
    partners_list = []
    for p in partners_qs:
        customer_profile = getattr(p.user, "customer_profile", None)
        location = getattr(p.user, "location", None)
        is_busy = p.id in busy_partner_ids
        busy_info = busy_reasons.get(p.id, {})

        # Try to get labor details
        labor_details = getattr(p, "labor_details", None)

        # Calculate distance from agent's center
        distance_km = None
        if has_agent_location and location and location.latitude is not None and location.longitude is not None:
            distance_km = round(_haversine_km(
                agent_lat, agent_lng,
                float(location.latitude), float(location.longitude)
            ), 1)

        # Distance filter
        if distance_filter:
            try:
                max_km = float(distance_filter)
                if distance_km is None or distance_km > max_km:
                    continue
            except (ValueError, TypeError):
                pass

        skills_list = [s.get_name('mr') for s in labor_details.service_types.all()] if labor_details else []

        partners_list.append({
            "partner": p,
            "full_name": customer_profile.full_name if customer_profile else "",
            "phone": p.user.phone_number,
            "gender": customer_profile.get_gender_display() if customer_profile and customer_profile.gender else "",
            "address": location.address if location else "",
            "partner_type": p.get_partner_type_display(),
            "partner_type_raw": p.partner_type,
            "is_busy": is_busy,
            "busy_reason": busy_info.get("reason", ""),
            "busy_marked_by": busy_info.get("marked_by", ""),
            "busy_is_system": busy_info.get("is_system", False),
            "rating": p.rating,
            "jobs_completed": p.jobs_completed,
            "skills": ", ".join(skills_list),
            "skills_list": skills_list,
            "daily_wage": labor_details.daily_wage_estimate if labor_details else None,
            "distance_km": distance_km,
        })

    # Sorting
    if sort_by == "wage_asc":
        partners_list.sort(key=lambda x: (x["daily_wage"] or 99999,))
    elif sort_by == "wage_desc":
        partners_list.sort(key=lambda x: (-(x["daily_wage"] or 0),))
    elif sort_by == "distance":
        partners_list.sort(key=lambda x: (x["distance_km"] if x["distance_km"] is not None else 99999,))
    elif sort_by == "rating":
        partners_list.sort(key=lambda x: (-float(x["rating"]),))

    available_count = sum(1 for p in partners_list if not p["is_busy"])
    busy_count = sum(1 for p in partners_list if p["is_busy"])

    # Filter options
    categories = Category.objects.filter(is_active=True).order_by('name')
    all_labor_skills = LaborServiceType.objects.filter(is_active=True).order_by('name')
    gender_choices = CustomerProfile.Gender.choices

    params = {
        "view": view_mode, "date": selected_date.isoformat(),
        "type": partner_type_filter, "q": search_q, "gender": gender_filter,
        "skills": skills_filter, "category": category_filter,
        "distance": distance_filter, "sort": sort_by,
    }
    bookings = Booking.objects.select_related(
        "customer", "customer__customer_profile", "provider__user", "service", "category",
    ).order_by("-created_at")
    context = {
        "page_title": "Availability",
        "view_mode": view_mode,
        "today_url": _availability_url(params, date=today.isoformat()),
        "clear_advanced_url": _availability_url(
            params, gender="", skills="", category="", distance="", sort="",
        ),
        "pending_bookings": bookings.filter(status=Booking.Status.SEARCHING)[:5],
        "active_bookings": bookings.filter(
            status__in=[Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS],
        )[:5],
        "selected_date": selected_date,
        "selected_date_str": selected_date.strftime("%Y-%m-%d"),
        "selected_date_display": selected_date.strftime("%A, %d %B %Y"),
        "partners_list": partners_list,
        "available_count": available_count,
        "busy_count": busy_count,
        "total_count": len(partners_list),
        "partner_type_filter": partner_type_filter,
        "partner_type_choices": PartnerProfile.PartnerType.choices,
        "gender_filter": gender_filter,
        "gender_choices": gender_choices,
        "skills_filter": skills_filter,
        "all_labor_skills": all_labor_skills,
        "category_filter": category_filter,
        "categories": categories,
        "distance_filter": distance_filter,
        "sort_by": sort_by,
        "search_q": search_q,
        "today": today,
        "has_agent_location": has_agent_location,
    }
    if view_mode == "calendar":
        context.update(_availability_calendar(
            selected_date, today, [item["partner"].pk for item in partners_list], params,
        ))
    return render(request, "adminpanel/availability.html", context)
