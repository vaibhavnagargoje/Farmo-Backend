"""Provider profile and labor, machinery, and transport updates."""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from labor_services.models import LaborDetails
from partners.models import MachineryDetails, PartnerProfile, TransportDetails
from users.models import User

from ..forms import (
    LaborDetailsAdminForm,
    MachineryDetailsAdminForm,
    PartnerProfileAdminForm,
    TransportDetailsAdminForm,
)
from ..permissions import is_agent


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
