"""Panel authentication and the existing Django admin login rate limit."""

from django.contrib.admin import site
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.core.cache import cache
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse

from ..permissions import is_agent


MAX_LOGIN_ATTEMPTS = 5


LOCKOUT_TIME = 600  # 10 minutes


def get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0]
    return request.META.get("REMOTE_ADDR")


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
