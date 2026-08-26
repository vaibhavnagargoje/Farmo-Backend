from django.contrib import messages
from django.contrib.admin import site
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from locations.models import UserLocation
from partners.models import MachineryDetails, PartnerProfile, TransportDetails
from labor_services.models import LaborDetails, LaborServiceType
from services.models import Category, Service, ServiceImage
from users.models import CustomerProfile, User

from .forms import (
    AddUserForm,
    CustomerProfileAdminForm,
    LaborDetailsAdminForm,
    MachineryDetailsAdminForm,
    PartnerProfileAdminForm,
    ServiceAdminForm,
    ServiceImageAdminForm,
    TransportDetailsAdminForm,
    UserInfoForm,
    UserLocationForm,
)
from .models import AgentPartnerRegistration

# ─────────────────────────────────────────────────────────────────────────────
# Auth helpers
# ─────────────────────────────────────────────────────────────────────────────

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_TIME = 600  # 10 minutes


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    return request.META.get("REMOTE_ADDR")


def is_agent(user):
    """Admin, SuperAdmin, and Verification Manager can all access the panel."""
    if not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser or user.role in {
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
        User.Role.MANAGER,
    }


# ─────────────────────────────────────────────────────────────────────────────
# RBAC helpers — role-change & active-toggle permission matrix
# ─────────────────────────────────────────────────────────────────────────────

def _get_actor_role(actor):
    """Resolve effective role: is_superuser maps to SUPERADMIN."""
    if actor.is_superuser:
        return User.Role.SUPERADMIN
    return actor.role


def get_allowed_role_targets(actor, target_user):
    """
    Return a set of Role *values* (strings) the actor may assign to target_user.

    Permission matrix:
      SuperAdmin  → any role on any user
      Admin       → CUSTOMER → {CUSTOMER, PARTNER}
                     MANAGER  → {MANAGER, ADMIN}
                     (cannot touch PARTNER, ADMIN, or SUPERADMIN targets)
      Manager     → CUSTOMER → {CUSTOMER, PARTNER}
                     (cannot touch any other target role)
    """
    actor_role = _get_actor_role(actor)
    target_role = target_user.role

    if actor_role == User.Role.SUPERADMIN:
        return {val for val, _ in User.Role.choices}

    if actor_role == User.Role.ADMIN:
        if target_role == User.Role.CUSTOMER:
            return {User.Role.CUSTOMER, User.Role.PARTNER}
        if target_role == User.Role.MANAGER:
            return {User.Role.MANAGER, User.Role.ADMIN}
        # PARTNER / ADMIN / SUPERADMIN targets — cannot touch
        return set()

    if actor_role == User.Role.MANAGER:
        if target_role == User.Role.CUSTOMER:
            return {User.Role.CUSTOMER, User.Role.PARTNER}
        return set()

    return set()


def get_allowed_role_choices(actor, target_user):
    """Filtered (value, label) pairs for the role dropdown in the template."""
    allowed_values = get_allowed_role_targets(actor, target_user)
    return [(val, label) for val, label in User.Role.choices if val in allowed_values]


def _can_toggle_active(actor, target_user):
    """
    Returns True if actor may flip the is_active flag on target_user.
      SuperAdmin  → anyone
      Admin       → anyone EXCEPT SuperAdmin accounts
      Manager     → nobody
    """
    actor_role = _get_actor_role(actor)
    if actor_role == User.Role.SUPERADMIN:
        return True
    if actor_role == User.Role.ADMIN:
        return target_user.role != User.Role.SUPERADMIN
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Legacy VLE helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_registration_progress(registration):
    partner_profile = registration.partner_profile
    if partner_profile is None:
        try:
            partner_profile = registration.registered_user.partner_profile
        except PartnerProfile.DoesNotExist:
            partner_profile = None

    has_partner_profile = bool(partner_profile)
    partner_type = registration.partner_type or (partner_profile.partner_type if partner_profile else None)
    has_labor_details = False

    if has_partner_profile and partner_type == PartnerProfile.PartnerType.LABOR:
        try:
            partner_profile.labor_details
            has_labor_details = True
        except LaborDetails.DoesNotExist:
            has_labor_details = False

    if not has_partner_profile:
        return {
            "status_label": "प्रोफाइल अपूर्ण",
            "status_tone": "amber",
            "action_label": "प्रोफाइल पूर्ण करा",
            "action_url": reverse(
                "adminpanel:create-worker-profile",
                kwargs={"user_id": registration.registered_user_id},
            ),
        }

    if partner_type == PartnerProfile.PartnerType.LABOR and not has_labor_details:
        return {
            "status_label": "कामगार तपशील अपूर्ण",
            "status_tone": "amber",
            "action_label": "तपशील पूर्ण करा",
            "action_url": reverse(
                "adminpanel:worker-details",
                kwargs={"user_id": registration.registered_user_id},
            ),
        }

    return {
        "status_label": "पूर्ण",
        "status_tone": "emerald",
        "action_label": "पाहा / अपडेट",
        "action_url": reverse(
            "adminpanel:registration-next",
            kwargs={"user_id": registration.registered_user_id},
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Admin Panel Login / Logout
# ─────────────────────────────────────────────────────────────────────────────

from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout


def panel_login(request):
    """
    Custom login page for the Farmo admin panel.
    Only ADMIN, SUPERADMIN, and MANAGER roles may sign in here.
    """
    # Already authenticated staff — go straight to dashboard
    if request.user.is_authenticated and is_agent(request.user):
        return redirect(reverse("adminpanel:dashboard"))

    error = None

    if request.method == "POST":
        phone = request.POST.get("phone_number", "").strip()
        password = request.POST.get("password", "").strip()

        # Rate-limit by IP (re-uses the existing counter mechanism)
        ip = get_client_ip(request)
        cache_key = f"panel_login_attempts_{ip}"
        attempts = cache.get(cache_key, 0)

        if attempts >= MAX_LOGIN_ATTEMPTS:
            error = "Too many failed attempts. Please wait 10 minutes and try again."
        elif not phone or not password:
            error = "Phone number and password are required."
        else:
            user = authenticate(request, username=phone, password=password)
            if user is None:
                cache.set(cache_key, attempts + 1, LOCKOUT_TIME)
                error = "Invalid phone number or password."
            elif not is_agent(user):
                error = "Your account does not have panel access."
            elif not user.is_active:
                error = "Your account has been deactivated. Contact a Super Admin."
            else:
                cache.delete(cache_key)
                auth_login(request, user)
                next_url = request.POST.get("next") or request.GET.get("next") or ""
                # Safety check — only allow relative redirects
                if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect(reverse("adminpanel:dashboard"))

    return render(request, "adminpanel/login.html", {
        "error": error,
        "next": request.GET.get("next", ""),
    })


def panel_logout(request):
    """Log out and redirect to the panel login page."""
    auth_logout(request)
    return redirect(reverse("adminpanel:login"))


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def dashboard(request):
    import calendar as cal_module
    from collections import defaultdict
    from datetime import date

    from availability.models import BusyDay
    from bookings.models import Booking

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

    # ── Filters (Either LABOR or MACHINERY) ──
    partner_type_filter = request.GET.get("partner_type", PartnerProfile.PartnerType.LABOR)
    if partner_type_filter not in [PartnerProfile.PartnerType.LABOR, PartnerProfile.PartnerType.MACHINERY_OWNER]:
        partner_type_filter = PartnerProfile.PartnerType.LABOR

    gender_filter = request.GET.get("gender", "")
    skills_filter = request.GET.get("skills", "").strip()
    category_filter = request.GET.get("category", "")

    # ── Stats (admin only) ──
    total_users = User.objects.count()
    total_partners = PartnerProfile.objects.count()
    total_services = Service.objects.count()
    active_services = Service.objects.filter(status=Service.Status.ACTIVE).count()
    pending_kyc = PartnerProfile.objects.filter(is_verified=False, is_kyc_submitted=True).count()

    # ── Filtered Partners Base QuerySet ──
    from django.db.models import Count

    if partner_type_filter == PartnerProfile.PartnerType.LABOR:
        partners_qs = PartnerProfile.objects.filter(
            is_available=True,
            partner_type=PartnerProfile.PartnerType.LABOR,
        )
        if gender_filter:
            partners_qs = partners_qs.filter(user__customer_profile__gender=gender_filter)
        if skills_filter:
            if skills_filter.isdigit():
                partners_qs = partners_qs.filter(labor_details__service_types__id=int(skills_filter))
            else:
                partners_qs = partners_qs.filter(
                    Q(labor_details__service_types__name__icontains=skills_filter)
                    | Q(labor_details__service_types__name_translations__icontains=skills_filter)
                ).distinct()
    else:  # MACHINERY
        partners_qs = PartnerProfile.objects.filter(
            is_available=True,
            partner_type=PartnerProfile.PartnerType.MACHINERY_OWNER,
        )
        if category_filter:
            partners_qs = partners_qs.filter(
                services__category_id=category_filter,
                services__status=Service.Status.ACTIVE,
            ).distinct()

    total_filtered_count = partners_qs.count()

    # ── Build calendar grid ──
    cal = cal_module.Calendar(firstweekday=0)  # Monday first (Sunday last)
    month_days = cal.monthdayscalendar(year, month)

    # Get days in this month
    _, num_days = cal_module.monthrange(year, month)

    # Busy counts per day for the selected partners
    busy_counts = BusyDay.objects.filter(
        date__year=year,
        date__month=month,
        partner__in=partners_qs,
    ).values('date__day').annotate(cnt=Count('partner_id', distinct=True))
    busy_per_day = {row['date__day']: row['cnt'] for row in busy_counts}

    # Booking counts per day
    booking_per_day = defaultdict(int)
    booking_counts = Booking.objects.filter(
        scheduled_date__year=year,
        scheduled_date__month=month,
    ).exclude(
        status__in=[Booking.Status.CANCELLED, Booking.Status.EXPIRED],
    ).values('scheduled_date__day').annotate(cnt=Count('id'))
    for row in booking_counts:
        booking_per_day[row['scheduled_date__day']] = row['cnt']

    # Build day_data dict
    day_data = {}
    for d in range(1, num_days + 1):
        day_date = date(year, month, d)
        is_past = day_date < today
        busy = busy_per_day.get(d, 0)
        free = max(0, total_filtered_count - busy)
        day_data[d] = {
            "free": free,
            "busy": busy,
            "total": total_filtered_count,
            "bookings": booking_per_day.get(d, 0),
            "is_past": is_past,
        }

    # Available today for stats row
    busy_today_count = BusyDay.objects.filter(
        date=today, service__isnull=True,
    ).values('partner_id').distinct().count()
    active_partners = PartnerProfile.objects.filter(is_available=True).count()
    available_today = max(0, active_partners - busy_today_count)

    # ── Previous/next month ──
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

    # ── Bookings feed (right panel) ──
    recent_bookings = Booking.objects.select_related(
        'customer', 'customer__customer_profile', 'provider', 'service', 'category',
    ).order_by('-created_at')[:10]

    pending_bookings = Booking.objects.filter(
        status__in=[Booking.Status.PENDING, Booking.Status.SEARCHING],
    ).select_related(
        'customer', 'customer__customer_profile', 'service', 'category',
    ).order_by('-created_at')[:5]

    active_bookings = Booking.objects.filter(
        status__in=[Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS],
    ).select_related(
        'customer', 'customer__customer_profile', 'provider', 'service', 'category',
    ).order_by('-created_at')[:5]

    # ── Filter options for template ──
    categories = Category.objects.filter(is_active=True).order_by('name')
    all_labor_skills = LaborServiceType.objects.filter(is_active=True).order_by('name')
    gender_choices = CustomerProfile.Gender.choices
    partner_type_choices = PartnerProfile.PartnerType.choices

    # Build filter query string for day-click links
    filter_params = f"&type={partner_type_filter}"
    if partner_type_filter == PartnerProfile.PartnerType.LABOR:
        if gender_filter:
            filter_params += f"&gender={gender_filter}"
        if skills_filter:
            filter_params += f"&skills={skills_filter}"
    elif partner_type_filter == PartnerProfile.PartnerType.MACHINERY_OWNER:
        if category_filter:
            filter_params += f"&category={category_filter}"

    context = {
        "page_title": "Dashboard",
        # Stats
        "total_users": total_users,
        "total_partners": total_partners,
        "total_services": total_services,
        "active_services": active_services,
        "pending_kyc": pending_kyc,
        "available_today": available_today,
        "active_partners": active_partners,
        # Calendar
        "year": year,
        "month": month,
        "month_name": month_name,
        "month_days": month_days,
        "day_data": day_data,
        "today": today,
        "prev_year": prev_year,
        "prev_month": prev_month,
        "next_year": next_year,
        "next_month": next_month,
        "weekdays": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        # Filters
        "partner_type_filter": partner_type_filter,
        "gender_filter": gender_filter,
        "skills_filter": skills_filter,
        "category_filter": category_filter,
        "categories": categories,
        "all_labor_skills": all_labor_skills,
        "gender_choices": gender_choices,
        "partner_type_choices": partner_type_choices,
        "filter_params": filter_params,
        # Bookings feed
        "recent_bookings": recent_bookings,
        "pending_bookings": pending_bookings,
        "active_bookings": active_bookings,
    }
    return render(request, "adminpanel/dashboard.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Users List
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def users_list(request):
    qs = User.objects.select_related("customer_profile", "location", "partner_profile").order_by("-date_joined")

    # Search
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(phone_number__icontains=q)
            | Q(email__icontains=q)
            | Q(customer_profile__full_name__icontains=q)
        )

    # Role filter
    role_filter = request.GET.get("role", "")
    if role_filter:
        qs = qs.filter(role=role_filter)

    # Status filter
    status_filter = request.GET.get("status", "")
    if status_filter == "no_profile":
        qs = qs.filter(customer_profile__isnull=True)
    elif status_filter == "no_partner":
        qs = qs.filter(partner_profile__isnull=True, role=User.Role.PARTNER)
    elif status_filter == "unverified":
        qs = qs.filter(partner_profile__is_verified=False, partner_profile__is_kyc_submitted=True)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "page_title": "Users",
        "page_obj": page_obj,
        "q": q,
        "role_filter": role_filter,
        "status_filter": status_filter,
        "role_choices": User.Role.choices,
        "total_count": paginator.count,
    }
    return render(request, "adminpanel/users_list.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Add User
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_http_methods(["GET", "POST"])
def add_user(request):
    """
    Admin creates a new Customer user with CustomerProfile and optional UserLocation
    in a single combined form, all within one atomic transaction.

    Role is always CUSTOMER — admins can change it later from the user detail page.
    No password is set; the user authenticates via OTP/phone.
    """
    form = AddUserForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                # 1. Create the User (role locked to CUSTOMER, unusable password)
                user = User(
                    phone_number=data["phone_number"],
                    email=data.get("email"),
                    role=User.Role.CUSTOMER,
                    preferred_language=data["preferred_language"],
                    is_active=data.get("is_active", True),
                )
                user.set_unusable_password()  # OTP-based auth — no password needed
                user.save()

                # 2. Create / update CustomerProfile
                # Signal auto-creates it for CUSTOMER role; get_or_create handles both cases.
                profile, _ = CustomerProfile.objects.get_or_create(user=user)
                if data.get("full_name"):
                    profile.full_name = data["full_name"]
                if data.get("gender"):
                    profile.gender = data["gender"]
                profile.save()

                # 3. Create UserLocation if any location data was provided
                if data.get("address") or data.get("latitude") or data.get("longitude"):
                    UserLocation.objects.create(
                        user=user,
                        address=data.get("address") or "",
                        latitude=data.get("latitude"),
                        longitude=data.get("longitude"),
                    )

            messages.success(
                request,
                f"User '{user.phone_number}' created successfully!",
            )
            return redirect("adminpanel:user-detail", user_id=user.pk)

        except IntegrityError as e:
            messages.error(request, f"Could not create user: {e}")

    return render(request, "adminpanel/add_user.html", {
        "page_title": "Add New User",
        "form": form,
    })


# ─────────────────────────────────────────────────────────────────────────────
# User Detail (read + multi-section edit)
# ─────────────────────────────────────────────────────────────────────────────

def _build_user_detail_context(user):
    """Build all data needed for the user detail page."""
    customer_profile = getattr(user, "customer_profile", None)
    location = getattr(user, "location", None)

    partner_profile = None
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        pass

    labor_details = None
    machinery_details = None
    transport_details = None
    services = []

    if partner_profile:
        try:
            labor_details = partner_profile.labor_details
        except LaborDetails.DoesNotExist:
            pass
        try:
            machinery_details = partner_profile.machinery_details
        except MachineryDetails.DoesNotExist:
            pass
        try:
            transport_details = partner_profile.transport_details
        except TransportDetails.DoesNotExist:
            pass
        services = partner_profile.services.select_related("category").prefetch_related("images").order_by("-created_at")

    return {
        "user": user,
        "customer_profile": customer_profile,
        "location": location,
        "partner_profile": partner_profile,
        "labor_details": labor_details,
        "machinery_details": machinery_details,
        "transport_details": transport_details,
        "services": services,
    }


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def user_detail(request, user_id):
    user = get_object_or_404(
        User.objects.select_related("customer_profile", "location"),
        pk=user_id,
    )
    ctx = _build_user_detail_context(user)

    # Pre-build forms for display (GET)
    ctx["user_info_form"] = UserInfoForm(instance=user)
    ctx["customer_profile_form"] = CustomerProfileAdminForm(instance=ctx["customer_profile"])

    location = ctx["location"]
    ctx["location_form"] = UserLocationForm(initial={
        "address": location.address if location else "",
        "latitude": location.latitude if location else "",
        "longitude": location.longitude if location else "",
    })

    ctx["partner_profile_form"] = PartnerProfileAdminForm(instance=ctx["partner_profile"])

    labor = ctx["labor_details"]
    ctx["labor_form"] = LaborDetailsAdminForm(instance=labor)

    machinery = ctx["machinery_details"]
    ctx["machinery_form"] = MachineryDetailsAdminForm(instance=machinery)

    transport = ctx["transport_details"]
    ctx["transport_form"] = TransportDetailsAdminForm(instance=transport)

    ctx["service_form"] = ServiceAdminForm()
    ctx["service_image_form"] = ServiceImageAdminForm()
    ctx["page_title"] = f"User — {user.phone_number}"
    ctx["categories"] = Category.objects.filter(is_active=True)

    # RBAC context — drives what the Login & System Status card shows
    ctx["allowed_role_choices"] = get_allowed_role_choices(request.user, user)
    ctx["can_change_role"] = bool(ctx["allowed_role_choices"])
    ctx["can_toggle_active"] = _can_toggle_active(request.user, user)

    return render(request, "adminpanel/user_detail.html", ctx)


# ─── Sub-section update views ─────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_user_info(request, user_id):
    """
    RBAC-enforced update of a user's role and/or active status.
    Every permission is checked server-side regardless of what the template renders,
    so direct POST attacks are also blocked.
    """
    target = get_object_or_404(User, pk=user_id)
    actor = request.user
    fields_changed = []

    # ── Role change ───────────────────────────────────────────────────────
    new_role = request.POST.get("role", "").strip()
    if new_role and new_role != target.role:
        allowed_values = get_allowed_role_targets(actor, target)
        if new_role not in allowed_values:
            messages.error(request, "You do not have permission to assign that role.")
            return redirect("adminpanel:user-detail", user_id=user_id)
        target.role = new_role
        fields_changed.append("role")

    # ── Active / inactive toggle ─────────────────────────────────────────────
    # Only process if the form sent the sentinel field — distinguishes
    # a deliberate is_active update from a form that simply didn't include it.
    if request.POST.get("is_active_submitted") == "1":
        if not _can_toggle_active(actor, target):
            messages.error(request, "You do not have permission to change this user's active status.")
            return redirect("adminpanel:user-detail", user_id=user_id)
        new_active = "is_active" in request.POST
        if target.is_active != new_active:
            target.is_active = new_active
            fields_changed.append("is_active")

    if fields_changed:
        target.save(update_fields=fields_changed)
        messages.success(request, "User settings updated.")

    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_customer_profile(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    profile = getattr(user, "customer_profile", None)
    form = CustomerProfileAdminForm(request.POST, request.FILES, instance=profile)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.user = user
        obj.save()
        messages.success(request, "Customer profile saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_user_location(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    form = UserLocationForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        UserLocation.objects.update_or_create(
            user=user,
            defaults={
                "address": data.get("address") or "",
                "latitude": data.get("latitude"),
                "longitude": data.get("longitude"),
            },
        )
        messages.success(request, "Location saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_partner_profile(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    profile = None
    try:
        profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        pass

    form = PartnerProfileAdminForm(request.POST, request.FILES, instance=profile)
    if form.is_valid():
        with transaction.atomic():
            pp = form.save(commit=False)
            pp.user = user
            pp.save()
            # Promote role to PARTNER if not already privileged
            if user.role == User.Role.CUSTOMER:
                user.role = User.Role.PARTNER
                user.save(update_fields=["role"])
        messages.success(request, "Partner profile saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_labor_details(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "Create a partner profile first.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    instance = None
    try:
        instance = partner_profile.labor_details
    except LaborDetails.DoesNotExist:
        pass

    form = LaborDetailsAdminForm(request.POST, request.FILES, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.partner = partner_profile
        obj.save()
        form.save_m2m()
        messages.success(request, "Labor details saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_machinery_details(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "Create a partner profile first.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    instance = None
    try:
        instance = partner_profile.machinery_details
    except MachineryDetails.DoesNotExist:
        pass

    form = MachineryDetailsAdminForm(request.POST, request.FILES, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.partner = partner_profile
        obj.save()
        messages.success(request, "Machinery details saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def update_transport_details(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "Create a partner profile first.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    instance = None
    try:
        instance = partner_profile.transport_details
    except TransportDetails.DoesNotExist:
        pass

    form = TransportDetailsAdminForm(request.POST, request.FILES, instance=instance)
    if form.is_valid():
        obj = form.save(commit=False)
        obj.partner = partner_profile
        obj.save()
        messages.success(request, "Transport details saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_http_methods(["GET", "POST"])
def service_create(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, "This user has no partner profile. Create one first.")
        return redirect("adminpanel:user-detail", user_id=user_id)

    form = ServiceAdminForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        service = form.save(commit=False)
        service.partner = partner_profile
        service.save()
        messages.success(request, f"Service '{service.title}' created.")
        return redirect("adminpanel:service-edit", user_id=user_id, service_id=service.id)

    return render(request, "adminpanel/service_form.html", {
        "page_title": "Add Service",
        "form": form,
        "user": user,
        "partner_profile": partner_profile,
        "creating": True,
    })


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_http_methods(["GET", "POST"])
def service_edit(request, user_id, service_id):
    user = get_object_or_404(User, pk=user_id)
    service = get_object_or_404(Service, pk=service_id, partner__user=user)

    form = ServiceAdminForm(request.POST or None, instance=service)
    image_form = ServiceImageAdminForm()

    if request.method == "POST" and "save_service" in request.POST and form.is_valid():
        form.save()
        messages.success(request, "Service updated.")
        return redirect("adminpanel:service-edit", user_id=user_id, service_id=service_id)

    images = service.images.all()

    return render(request, "adminpanel/service_form.html", {
        "page_title": f"Edit Service — {service.title}",
        "form": form,
        "image_form": image_form,
        "user": user,
        "service": service,
        "images": images,
        "creating": False,
    })


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def service_image_upload(request, user_id, service_id):
    service = get_object_or_404(Service, pk=service_id, partner__user__pk=user_id)
    form = ServiceImageAdminForm(request.POST, request.FILES)
    if form.is_valid():
        img = form.save(commit=False)
        img.service = service
        # If marked thumbnail, unset others
        if img.is_thumbnail:
            service.images.update(is_thumbnail=False)
        img.save()
        messages.success(request, "Image uploaded.")
    else:
        messages.error(request, "Invalid image upload.")
    return redirect("adminpanel:service-edit", user_id=user_id, service_id=service_id)


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
@require_POST
def service_image_delete(request, user_id, service_id, image_id):
    image = get_object_or_404(ServiceImage, pk=image_id, service__pk=service_id, service__partner__user__pk=user_id)
    image.delete()
    messages.success(request, "Image deleted.")
    return redirect("adminpanel:service-edit", user_id=user_id, service_id=service_id)





# ─────────────────────────────────────────────────────────────────────────────
# Calendar / Availability Management
# ─────────────────────────────────────────────────────────────────────────────

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

    from bookings.models import Booking, InstantBookingRequest
    pending_scheduled_bookings = Booking.objects.filter(
        provider=partner_profile, 
        status__in=[Booking.Status.PENDING, Booking.Status.SEARCHING]
    ).select_related('customer', 'customer__customer_profile', 'service', 'category').order_by('scheduled_date', '-created_at')

    pending_instant_requests = InstantBookingRequest.objects.filter(
        provider=partner_profile, 
        status=InstantBookingRequest.RequestStatus.PENDING
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
        "pending_scheduled_bookings": pending_scheduled_bookings,
        "pending_instant_requests": pending_instant_requests,
        "active_bookings": active_bookings,
    }
    return render(request, "adminpanel/worker_calendar.html", context)


from django.views.decorators.http import require_POST
from django.db import transaction
from bookings.models import Booking, InstantBookingRequest
from django.utils import timezone

@require_POST
@user_passes_test(is_agent, login_url='/api/v1/admin/login/')
def agent_worker_booking_action(request, user_id):
    """
    Allow an admin to accept or reject a booking on behalf of the partner.
    """
    user = get_object_or_404(User, pk=user_id)
    try:
        partner_profile = user.partner_profile
    except PartnerProfile.DoesNotExist:
        messages.error(request, 'This user has no partner profile.')
        return redirect('adminpanel:worker-calendar', user_id=user_id)
        
    booking_id = request.POST.get('booking_id')
    req_id = request.POST.get('request_id')
    action = request.POST.get('action') # 'accept' or 'reject'
    booking_type = request.POST.get('type') # 'scheduled' or 'instant'
    
    if action not in ['accept', 'reject']:
        messages.error(request, 'Invalid action.')
        return redirect('adminpanel:worker-calendar', user_id=user_id)
        
    if booking_type == 'scheduled' and booking_id:
        booking = get_object_or_404(Booking, booking_id=booking_id, provider=partner_profile)
        if action == 'accept':
            booking.status = Booking.Status.CONFIRMED
            booking.accepted_by_agent = request.user
            booking.save()
            messages.success(request, f'Scheduled Booking {booking_id} accepted on behalf of partner.')
        elif action == 'reject':
            booking.status = Booking.Status.REJECTED
            booking.cancelled_by = request.user
            booking.cancellation_reason = 'Rejected by agent on behalf of provider'
            booking.save()
            messages.success(request, f'Scheduled Booking {booking_id} rejected.')
            
    elif booking_type == 'instant' and req_id:
        with transaction.atomic():
            try:
                instant_req = InstantBookingRequest.objects.select_for_update().get(pk=req_id, provider=partner_profile)
            except InstantBookingRequest.DoesNotExist:
                messages.error(request, 'Request not found.')
                return redirect('adminpanel:worker-calendar', user_id=user_id)
                
            if instant_req.status != InstantBookingRequest.RequestStatus.PENDING:
                messages.error(request, 'This request has already been responded to.')
                return redirect('adminpanel:worker-calendar', user_id=user_id)
                
            booking = Booking.objects.select_for_update().get(pk=instant_req.booking_id)
            
            if action == 'accept':
                if booking.status != Booking.Status.SEARCHING:
                    instant_req.status = InstantBookingRequest.RequestStatus.EXPIRED
                    instant_req.responded_at = timezone.now()
                    instant_req.save(update_fields=['status', 'responded_at'])
                    messages.error(request, 'This booking is no longer available.')
                    return redirect('adminpanel:worker-calendar', user_id=user_id)
                    
                booking.provider = partner_profile
                booking.status = Booking.Status.CONFIRMED
                booking.assigned_at = timezone.now()
                booking.accepted_by_agent = request.user
                booking.save()
                
                instant_req.status = InstantBookingRequest.RequestStatus.ACCEPTED
                instant_req.responded_at = timezone.now()
                instant_req.save(update_fields=['status', 'responded_at'])
                
                # Expire others
                InstantBookingRequest.objects.filter(
                    booking=booking, status=InstantBookingRequest.RequestStatus.PENDING
                ).exclude(pk=req_id).update(
                    status=InstantBookingRequest.RequestStatus.EXPIRED, responded_at=timezone.now()
                )
                messages.success(request, f'Instant Booking accepted on behalf of partner.')
                
            elif action == 'reject':
                instant_req.status = InstantBookingRequest.RequestStatus.DECLINED
                instant_req.responded_at = timezone.now()
                instant_req.save(update_fields=['status', 'responded_at'])
                messages.success(request, 'Instant Booking request declined.')
                
    else:
        messages.error(request, 'Invalid data provided.')
        
    return redirect('adminpanel:worker-calendar', user_id=user_id)

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


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def agent_workers_by_date(request):
    """
    Shows all workers and their availability for a selected date.
    Agent can see who is free and who is busy at a glance.
    Enhanced with gender, skills, category, distance, and wage sort filters.
    """
    from datetime import date, datetime
    from availability.models import BusyDay
    from locations.pricing import _haversine_km

    today = date.today()
    date_str = request.GET.get("date", "")
    try:
        selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        selected_date = today

    # Filters
    partner_type_filter = request.GET.get("type", "")
    search_q = request.GET.get("q", "").strip()
    gender_filter = request.GET.get("gender", "")
    skills_filter = request.GET.get("skills", "").strip()
    category_filter = request.GET.get("category", "")
    distance_filter = request.GET.get("distance", "")  # km radius
    sort_by = request.GET.get("sort", "")  # wage_asc, wage_desc, distance, rating

    # Get all active partners (is_available=True master switch)
    partners_qs = PartnerProfile.objects.filter(
        is_available=True,
    ).select_related(
        "user", "user__customer_profile", "user__location",
    ).order_by("user__customer_profile__full_name", "user__phone_number")

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
    agent_lat = float(agent_location.latitude) if agent_location and agent_location.latitude else None
    agent_lng = float(agent_location.longitude) if agent_location and agent_location.longitude else None

    # Build partner list with availability status
    partners_list = []
    for p in partners_qs:
        customer_profile = getattr(p.user, "customer_profile", None)
        location = getattr(p.user, "location", None)
        is_busy = p.id in busy_partner_ids
        busy_info = busy_reasons.get(p.id, {})

        # Try to get labor details
        labor_details = None
        try:
            labor_details = p.labor_details
        except Exception:
            pass

        # Calculate distance from agent's center
        distance_km = None
        if agent_lat and agent_lng and location and location.latitude and location.longitude:
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

    context = {
        "page_title": "Workers by Date",
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
        "has_agent_location": bool(agent_lat and agent_lng),
    }
    return render(request, "adminpanel/workers_by_date.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Rate-limited Django admin login (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

original_django_admin_login = site.login


def rate_limited_django_admin_login(request, *args, **kwargs):
    if request.method == "POST":
        ip = get_client_ip(request)
        cache_key = f"django_admin_login_attempts_{ip}"
        attempts = cache.get(cache_key, 0)
        if attempts >= MAX_LOGIN_ATTEMPTS:
            return HttpResponseForbidden("Too many failing login attempts. Please try again later.")
        response = original_django_admin_login(request, *args, **kwargs)
        if response.status_code == 302:
            cache.delete(cache_key)
        else:
            cache.set(cache_key, attempts + 1, LOCKOUT_TIME)
        return response
    return original_django_admin_login(request, *args, **kwargs)
