from django.contrib import messages
from django.contrib.admin import site
from django.contrib.auth.decorators import user_passes_test
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpResponseForbidden
from django.urls import reverse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from locations.models import UserLocation
from partners.models import LaborDetails, PartnerProfile
from users.models import CustomerProfile, User

from .forms import AgentUserRegistrationForm, LaborDetailsForm, WorkerPartnerProfileForm
from .models import AgentPartnerRegistration

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


@user_passes_test(is_agent, login_url="/admin/login/")
def dashboard(request):
    my_registrations = AgentPartnerRegistration.objects.filter(agent=request.user).select_related(
        "registered_user",
        "registered_user__customer_profile",
        "registered_user__location",
        "partner_profile",
    )
    recent_registrations = []
    for registration in my_registrations[:10]:
        progress = _get_registration_progress(registration)
        registration.status_label = progress["status_label"]
        registration.status_tone = progress["status_tone"]
        registration.action_label = progress["action_label"]
        registration.action_url = progress["action_url"]
        recent_registrations.append(registration)

    context = {
        "page_title": "VLE डॅशबोर्ड",
        "my_total_registered": my_registrations.count(),
        "my_worker_registered": my_registrations.filter(
            partner_type=PartnerProfile.PartnerType.LABOR
        ).count(),
        "my_machinery_registered": my_registrations.filter(
            partner_type=PartnerProfile.PartnerType.MACHINERY_OWNER
        ).count(),
        "recent_registrations": recent_registrations,
    }
    return render(request, "adminpanel/dashboard.html", context)


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET", "POST"])
def register_user(request):
    form = AgentUserRegistrationForm(request.POST or None)

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
                    defaults={"full_name": data["full_name"]},
                )

                UserLocation.objects.update_or_create(
                    user=user,
                    defaults={
                        "address": data["address"],
                        "latitude": data.get("latitude"),
                        "longitude": data.get("longitude"),
                    },
                )

                AgentPartnerRegistration.objects.create(
                    agent=request.user,
                    registered_user=user,
                )
        except IntegrityError:
            messages.error(
                request,
                "वापरकर्ता तयार करता आला नाही. मोबाईल नंबर किंवा ईमेल आधीपासून नोंदणीकृत आहे का ते तपासा.",
            )
        else:
            messages.success(request, "वापरकर्ता यशस्वीरित्या तयार झाला. पुढील प्रोफाइल प्रक्रिया सुरू ठेवा.")
            return redirect("adminpanel:registration-next", user_id=user.id)

    return render(
        request,
        "adminpanel/register_user.html",
        {
            "page_title": "वापरकर्ता नोंदणी",
            "form": form,
        },
    )


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
            has_labor_details = False

    context = {
        "page_title": "पुढील पायरी",
        "registration": registration,
        "has_partner_profile": has_partner_profile,
        "has_labor_details": has_labor_details,
    }
    return render(request, "adminpanel/registration_next.html", context)


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

    if partner_profile and partner_profile.partner_type not in {
        PartnerProfile.PartnerType.LABOR,
        None,
    }:
        messages.error(
            request,
            "या वापरकर्त्याचा कामगाराव्यतिरिक्त दुसऱ्या प्रकारचा पार्टनर प्रोफाइल आधीच आहे.",
        )
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

    context = {
        "page_title": "कामगार प्रोफाइल कागदपत्रे",
        "registration": registration,
        "form": form,
    }
    return render(request, "adminpanel/worker_profile_documents.html", context)


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
        labor_details = None

    form = LaborDetailsForm(request.POST or None, request.FILES or None, instance=labor_details)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            details = form.save(commit=False)
            details.partner = registration.partner_profile
            details.save()

        messages.success(request, "कामगार प्रोफाइल यशस्वीरित्या पूर्ण झाले.")
        return redirect("adminpanel:registration-next", user_id=user_id)

    context = {
        "page_title": "कामगार तपशील",
        "registration": registration,
        "form": form,
    }
    return render(request, "adminpanel/worker_labor_details.html", context)


@user_passes_test(is_agent, login_url="/admin/login/")
@require_http_methods(["GET"])
def create_machinery_profile_placeholder(request, user_id):
    registration = get_object_or_404(
        AgentPartnerRegistration,
        registered_user_id=user_id,
        agent=request.user,
    )
    messages.info(
        request,
        f"{registration.registered_user.phone_number} साठी मशिनरी लिस्टिंग फ्लो पुढील टप्प्यात जोडला जाईल.",
    )
    return redirect("adminpanel:registration-next", user_id=user_id)


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
