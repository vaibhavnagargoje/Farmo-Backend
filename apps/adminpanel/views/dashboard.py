"""Dashboard summary cards; detailed booking analytics live in the Bookings section."""

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.utils import timezone

from availability.models import BusyDay
from partners.models import PartnerProfile
from services.models import Service
from users.models import User

from ..booking_analytics import live_tiles
from ..permissions import is_agent


@user_passes_test(is_agent, login_url="/api/v1/admin/login/")
def dashboard(request):
    active_partners = PartnerProfile.objects.filter(is_available=True)
    busy_today = BusyDay.objects.filter(
        date=timezone.localdate(), service__isnull=True,
    ).values("partner_id")
    return render(request, "adminpanel/dashboard.html", {
        "page_title": "Dashboard",
        "total_users": User.objects.count(),
        "total_partners": PartnerProfile.objects.count(),
        "total_services": Service.objects.count(),
        "active_services": Service.objects.filter(status=Service.Status.ACTIVE).count(),
        "pending_kyc": PartnerProfile.objects.filter(
            is_verified=False, is_kyc_submitted=True,
        ).count(),
        "active_partners": active_partners.count(),
        "available_today": active_partners.exclude(pk__in=busy_today).count(),
        "booking_tiles": live_tiles(),
    })
