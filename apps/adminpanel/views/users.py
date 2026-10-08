"""User listing, registration, detail pages, and account updates."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from labor_services.models import (
    LaborDetails,
    LaborPriceUnit,
    LaborServiceOffering,
    LaborServiceType,
)
from locations.models import UserLocation
from partners.models import MachineryDetails, PartnerProfile, TransportDetails
from services.models import Category
from users.models import CustomerProfile, User

from ..forms import (
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
from ..permissions import (
    _can_toggle_active,
    get_allowed_role_choices,
    get_allowed_role_targets,
    is_agent,
)


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
                if data.get("date_of_birth"):
                    profile.date_of_birth = data["date_of_birth"]
                if data.get("age"):
                    profile.age = data["age"]
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
@require_http_methods(["GET", "POST"])
def user_detail(request, user_id):
    user = get_object_or_404(
        User.objects.select_related("customer_profile", "location"),
        pk=user_id,
    )
    actor = request.user
    allowed_role_choices = get_allowed_role_choices(actor, user)
    can_change_role = bool(allowed_role_choices)
    can_toggle_active = _can_toggle_active(actor, user)

    if request.method == "POST":
        errors = []
        try:
            with transaction.atomic():
                # ── 1. User Account Fields ────────────────────────────────
                # Role
                new_role = request.POST.get("role", "").strip()
                if new_role and new_role != user.role:
                    allowed_values = get_allowed_role_targets(actor, user)
                    if new_role in allowed_values:
                        user.role = new_role
                    else:
                        errors.append("You do not have permission to assign that role.")

                # Active Status
                if request.POST.get("is_active_submitted") == "1":
                    if can_toggle_active:
                        user.is_active = "is_active" in request.POST
                    else:
                        if user.is_active != ("is_active" in request.POST):
                            errors.append("You do not have permission to change this user's active status.")

                # Email
                new_email = request.POST.get("email", "").strip() or None
                if new_email != user.email:
                    if new_email and User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
                        errors.append("A user with this email address already exists.")
                    else:
                        user.email = new_email

                # Preferred Language
                new_lang = request.POST.get("preferred_language", "").strip()
                if new_lang in dict(User.Language.choices):
                    user.preferred_language = new_lang

                user.save()

                # ── 2. Customer Profile ───────────────────────────────────
                customer_profile, _ = CustomerProfile.objects.get_or_create(user=user)
                customer_form = CustomerProfileAdminForm(request.POST, request.FILES, instance=customer_profile)
                if customer_form.is_valid():
                    cp = customer_form.save(commit=False)
                    cp.user = user
                    if cp.date_of_birth and not cp.age:
                        from django.utils import timezone
                        today = timezone.now().date()
                        cp.age = max(0, today.year - cp.date_of_birth.year - ((today.month, today.day) < (cp.date_of_birth.month, cp.date_of_birth.day)))
                    cp.save()
                else:
                    for field, err_list in customer_form.errors.items():
                        errors.append(f"Personal Profile ({field}): {', '.join(err_list)}")

                # ── 3. User Location ──────────────────────────────────────
                address_val = request.POST.get("address", "").strip()
                lat_str = request.POST.get("latitude", "").strip()
                lng_str = request.POST.get("longitude", "").strip()
                lat_val = None
                lng_val = None
                if lat_str:
                    try:
                        lat_val = Decimal(lat_str)
                    except Exception:
                        errors.append("Invalid latitude value.")
                if lng_str:
                    try:
                        lng_val = Decimal(lng_str)
                    except Exception:
                        errors.append("Invalid longitude value.")

                if address_val or lat_val is not None or lng_val is not None:
                    UserLocation.objects.update_or_create(
                        user=user,
                        defaults={
                            "address": address_val,
                            "latitude": lat_val,
                            "longitude": lng_val,
                        },
                    )

                # ── 4. Partner Profile & Specific Details ─────────────────
                partner_profile = None
                try:
                    partner_profile = user.partner_profile
                except PartnerProfile.DoesNotExist:
                    pass

                should_save_partner = (user.role == User.Role.PARTNER) or (partner_profile is not None) or bool(request.POST.get("partner_type"))

                if should_save_partner:
                    if partner_profile is None:
                        partner_profile = PartnerProfile(user=user)

                    partner_form = PartnerProfileAdminForm(request.POST, request.FILES, instance=partner_profile)
                    if partner_form.is_valid():
                        pp = partner_form.save(commit=False)
                        pp.user = user
                        pp.save()
                    else:
                        for field, err_list in partner_form.errors.items():
                            errors.append(f"Partner Profile ({field}): {', '.join(err_list)}")

                    p_type = request.POST.get("partner_type") or partner_profile.partner_type

                    # Labor Details
                    if p_type == PartnerProfile.PartnerType.LABOR:
                        labor_details = getattr(partner_profile, "labor_details", None)
                        if labor_details is None:
                            try:
                                labor_details = partner_profile.labor_details
                            except Exception:
                                labor_details = None

                        labor_form = LaborDetailsAdminForm(request.POST, request.FILES, instance=labor_details)
                        if labor_form.is_valid():
                            ld = labor_form.save(commit=False)
                            ld.partner = partner_profile
                            ld.save()

                            # Sync service_types / LaborServiceOffering
                            raw_skills = request.POST.getlist("service_types")
                            skill_ids = {int(x) for x in raw_skills if x and str(x).isdigit()}
                            default_unit = LaborPriceUnit.objects.filter(is_active=True).first()

                            # Delete removed offerings
                            LaborServiceOffering.objects.filter(labor_details=ld).exclude(service_type_id__in=skill_ids).delete()
                            
                            # Add newly selected offerings
                            existing_skill_ids = set(LaborServiceOffering.objects.filter(labor_details=ld).values_list("service_type_id", flat=True))
                            for s_id in (skill_ids - existing_skill_ids):
                                try:
                                    st = LaborServiceType.objects.get(pk=s_id)
                                    u = st.default_price_unit or default_unit
                                    if u:
                                        LaborServiceOffering.objects.create(
                                            labor_details=ld,
                                            service_type=st,
                                            price=ld.daily_wage_estimate or 0,
                                            price_unit=u,
                                        )
                                except Exception:
                                    pass
                        else:
                            for field, err_list in labor_form.errors.items():
                                errors.append(f"Labor Details ({field}): {', '.join(err_list)}")

                    # Machinery Details
                    elif p_type == PartnerProfile.PartnerType.MACHINERY_OWNER:
                        machinery_details = getattr(partner_profile, "machinery_details", None)
                        if machinery_details is None:
                            try:
                                machinery_details = partner_profile.machinery_details
                            except Exception:
                                machinery_details = None

                        mach_form = MachineryDetailsAdminForm(request.POST, request.FILES, instance=machinery_details)
                        if mach_form.is_valid():
                            md = mach_form.save(commit=False)
                            md.partner = partner_profile
                            md.save()
                        else:
                            for field, err_list in mach_form.errors.items():
                                errors.append(f"Machinery Details ({field}): {', '.join(err_list)}")

                    # Transport Details
                    elif p_type == PartnerProfile.PartnerType.TRANSPORTER:
                        transport_details = getattr(partner_profile, "transport_details", None)
                        if transport_details is None:
                            try:
                                transport_details = partner_profile.transport_details
                            except Exception:
                                transport_details = None

                        trans_form = TransportDetailsAdminForm(request.POST, request.FILES, instance=transport_details)
                        if trans_form.is_valid():
                            td = trans_form.save(commit=False)
                            td.partner = partner_profile
                            td.save()
                        else:
                            for field, err_list in trans_form.errors.items():
                                errors.append(f"Transport Details ({field}): {', '.join(err_list)}")

                if errors:
                    raise ValueError("; ".join(errors))

                messages.success(request, f"User '{user.phone_number}' updated successfully.")
                return redirect("adminpanel:user-detail", user_id=user.pk)

        except Exception as e:
            messages.error(request, str(e))

    ctx = _build_user_detail_context(user)

    # Pre-build forms for display
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

    # RBAC context
    ctx["allowed_role_choices"] = allowed_role_choices
    ctx["can_change_role"] = can_change_role
    ctx["can_toggle_active"] = can_toggle_active

    # Google Maps API key
    from django.conf import settings as django_settings
    ctx["google_maps_key"] = django_settings.GOOGLE_MAPS_API_KEY

    return render(request, "adminpanel/user_detail.html", ctx)


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
