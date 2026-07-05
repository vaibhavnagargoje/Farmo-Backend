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
from partners.models import LaborDetails, MachineryDetails, PartnerProfile, TransportDetails
from services.models import Category, Service, ServiceImage
from users.models import CustomerProfile, User

from .forms import (
    AgentUserRegistrationForm,
    CustomerProfileAdminForm,
    LaborDetailsAdminForm,
    LaborDetailsForm,
    MachineryDetailsAdminForm,
    PartnerProfileAdminForm,
    ServiceAdminForm,
    ServiceImageAdminForm,
    TransportDetailsAdminForm,
    UserInfoForm,
    UserLocationForm,
    WorkerPartnerProfileForm,
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
    if not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser or user.role in {
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
    }


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
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
def dashboard(request):
    total_users = User.objects.count()
    total_partners = PartnerProfile.objects.count()
    total_services = Service.objects.count()
    active_services = Service.objects.filter(status=Service.Status.ACTIVE).count()
    # Partners who submitted KYC but admin hasn't verified yet
    pending_kyc = PartnerProfile.objects.filter(is_verified=False, is_kyc_submitted=True).count()
    # Users who have no CustomerProfile at all
    no_profile_users = User.objects.filter(customer_profile__isnull=True).count()
    # Partners with role=PARTNER but no PartnerProfile
    no_partner_profile = User.objects.filter(role=User.Role.PARTNER, partner_profile__isnull=True).count()

    context = {
        "page_title": "Dashboard",
        "total_users": total_users,
        "total_partners": total_partners,
        "total_services": total_services,
        "active_services": active_services,
        "pending_kyc": pending_kyc,
        "no_profile_users": no_profile_users,
        "no_partner_profile": no_partner_profile,
    }
    return render(request, "adminpanel/dashboard.html", context)


# ─────────────────────────────────────────────────────────────────────────────
# Users List
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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

    return render(request, "adminpanel/user_detail.html", ctx)


# ─── Sub-section update views ─────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
@require_POST
def update_user_info(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    form = UserInfoForm(request.POST, instance=user)
    if form.is_valid():
        form.save()
        messages.success(request, "User info updated.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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
        messages.success(request, "Labor details saved.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect("adminpanel:user-detail", user_id=user_id)


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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
# Add new user (from Users List page)
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET", "POST"])
def add_user(request):
    form = AgentUserRegistrationForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    phone_number=data["phone_number"],
                    password=None,
                    email=data.get("email") or None,
                    role=User.Role.CUSTOMER,
                    is_active=True,
                )
                CustomerProfile.objects.create(
                    user=user,
                    full_name=data["full_name"],
                    profile_picture=data.get("profile_picture"),
                )
                if data.get("address") or data.get("latitude"):
                    UserLocation.objects.create(
                        user=user,
                        address=data.get("address") or "",
                        latitude=data.get("latitude"),
                        longitude=data.get("longitude"),
                    )
        except IntegrityError:
            messages.error(request, "Could not create user — phone number or email already registered.")
        else:
            messages.success(request, f"User {data['phone_number']} created successfully.")
            return redirect("adminpanel:user-detail", user_id=user.id)

    return render(request, "adminpanel/add_user.html", {
        "page_title": "Add New User",
        "form": form,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Services
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
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


@user_passes_test(is_agent, login_url="/admin/login/")
@require_POST
def service_image_delete(request, user_id, service_id, image_id):
    image = get_object_or_404(ServiceImage, pk=image_id, service__pk=service_id, service__partner__user__pk=user_id)
    image.delete()
    messages.success(request, "Image deleted.")
    return redirect("adminpanel:service-edit", user_id=user_id, service_id=service_id)


# ─────────────────────────────────────────────────────────────────────────────
# Legacy VLE registration flow (preserved)
# ─────────────────────────────────────────────────────────────────────────────

@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET", "POST"])
def register_user(request):
    form = AgentUserRegistrationForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    phone_number=data["phone_number"],
                    password=None,
                    email=data.get("email") or None,
                    role=User.Role.PARTNER,
                    is_active=True,
                )
                CustomerProfile.objects.update_or_create(
                    user=user,
                    defaults={
                        "full_name": data["full_name"],
                        "profile_picture": data.get("profile_picture"),
                    },
                )
                UserLocation.objects.update_or_create(
                    user=user,
                    defaults={
                        "address": data.get("address") or "",
                        "latitude": data.get("latitude"),
                        "longitude": data.get("longitude"),
                    },
                )
                AgentPartnerRegistration.objects.create(
                    agent=request.user,
                    registered_user=user,
                )
        except IntegrityError:
            messages.error(request, "वापरकर्ता तयार करता आला नाही. मोबाईल नंबर किंवा ईमेल आधीपासून नोंदणीकृत आहे का ते तपासा.")
        else:
            messages.success(request, "वापरकर्ता यशस्वीरित्या तयार झाला. पुढील प्रोफाइल प्रक्रिया सुरू ठेवा.")
            return redirect("adminpanel:registration-next", user_id=user.id)

    return render(request, "adminpanel/register_user.html", {
        "page_title": "वापरकर्ता नोंदणी",
        "form": form,
    })


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET"])
def registration_next(request, user_id):
    registration = get_object_or_404(
        AgentPartnerRegistration.objects.select_related(
            "registered_user",
            "registered_user__customer_profile",
            "registered_user__location",
            "partner_profile",
        ),
        registered_user_id=user_id,
        agent=request.user,
    )
    has_partner_profile = bool(registration.partner_profile)
    has_labor_details = False
    if registration.partner_profile and registration.partner_type == PartnerProfile.PartnerType.LABOR:
        try:
            registration.partner_profile.labor_details
            has_labor_details = True
        except LaborDetails.DoesNotExist:
            pass

    return render(request, "adminpanel/registration_next.html", {
        "page_title": "पुढील पायरी",
        "registration": registration,
        "has_partner_profile": has_partner_profile,
        "has_labor_details": has_labor_details,
    })


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET", "POST"])
def create_worker_profile(request, user_id):
    registration = get_object_or_404(
        AgentPartnerRegistration.objects.select_related("registered_user", "partner_profile"),
        registered_user_id=user_id,
        agent=request.user,
    )
    partner_profile = registration.partner_profile
    if partner_profile is None:
        try:
            partner_profile = registration.registered_user.partner_profile
        except PartnerProfile.DoesNotExist:
            partner_profile = None

    if partner_profile and partner_profile.partner_type not in {PartnerProfile.PartnerType.LABOR, None}:
        messages.error(request, "या वापरकर्त्याचा कामगाराव्यतिरिक्त दुसऱ्या प्रकारचा पार्टनर प्रोफाइल आधीच आहे.")
        return redirect("adminpanel:registration-next", user_id=user_id)

    form = WorkerPartnerProfileForm(request.POST or None, request.FILES or None, instance=partner_profile)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            partner_profile = form.save(commit=False)
            partner_profile.user = registration.registered_user
            partner_profile.partner_type = PartnerProfile.PartnerType.LABOR
            partner_profile.is_kyc_submitted = True
            partner_profile.save()
            registration.partner_profile = partner_profile
            registration.partner_type = PartnerProfile.PartnerType.LABOR
            registration.save(update_fields=["partner_profile", "partner_type"])
        messages.success(request, "पार्टनर कागदपत्रे जतन झाली. आता कामगार तपशील पूर्ण करा.")
        return redirect("adminpanel:worker-details", user_id=user_id)

    return render(request, "adminpanel/worker_profile_documents.html", {
        "page_title": "कामगार प्रोफाइल कागदपत्रे",
        "registration": registration,
        "form": form,
    })


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET", "POST"])
def worker_details(request, user_id):
    registration = get_object_or_404(
        AgentPartnerRegistration.objects.select_related("registered_user", "partner_profile"),
        registered_user_id=user_id,
        agent=request.user,
    )
    if not registration.partner_profile:
        messages.error(request, "कृपया आधी पार्टनर प्रोफाइल कागदपत्रे पूर्ण करा.")
        return redirect("adminpanel:create-worker-profile", user_id=user_id)
    if registration.partner_profile.partner_type != PartnerProfile.PartnerType.LABOR:
        messages.error(request, "कामगार तपशील फक्त कामगार प्रोफाइलसाठी उपलब्ध आहेत.")
        return redirect("adminpanel:registration-next", user_id=user_id)

    labor_details = None
    try:
        labor_details = registration.partner_profile.labor_details
    except LaborDetails.DoesNotExist:
        pass

    form = LaborDetailsForm(request.POST or None, request.FILES or None, instance=labor_details)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            details = form.save(commit=False)
            details.partner = registration.partner_profile
            details.save()
        messages.success(request, "कामगार प्रोफाइल यशस्वीरित्या पूर्ण झाले.")
        return redirect("adminpanel:registration-next", user_id=user_id)

    return render(request, "adminpanel/worker_labor_details.html", {
        "page_title": "कामगार तपशील",
        "registration": registration,
        "form": form,
    })


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET"])
def create_machinery_profile_placeholder(request, user_id):
    registration = get_object_or_404(AgentPartnerRegistration, registered_user_id=user_id, agent=request.user)
    messages.info(request, f"{registration.registered_user.phone_number} साठी मशिनरी लिस्टिंग फ्लो पुढील टप्प्यात जोडला जाईल.")
    return redirect("adminpanel:registration-next", user_id=user_id)


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
