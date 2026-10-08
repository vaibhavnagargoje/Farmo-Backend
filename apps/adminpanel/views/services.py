"""Service creation, editing, and image management endpoints."""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from partners.models import PartnerProfile
from services.models import Service, ServiceImage
from users.models import User

from ..forms import ServiceAdminForm, ServiceImageAdminForm
from ..permissions import is_agent


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
