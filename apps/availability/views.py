# apps/availability/views.py
import calendar
from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from partners.models import PartnerProfile
from services.models import Service
from .models import BusyDay
from .serializers import ToggleBusyDaySerializer


class MyCalendarView(APIView):
    """
    GET /api/v1/availability/my-calendar/?month=8&year=2026

    Returns all busy dates for the logged-in partner for a given month.
    Response: { "year": 2026, "month": 8, "busy_dates": ["2026-08-06", "2026-08-07"] }
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            partner = request.user.partner_profile
        except PartnerProfile.DoesNotExist:
            return Response(
                {"error": "You are not registered as a partner."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.now().date()
        year = int(request.query_params.get('year', today.year))
        month = int(request.query_params.get('month', today.month))

        # Validate month/year
        if not (1 <= month <= 12) or year < 2020:
            return Response(
                {"error": "Invalid month or year."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get all busy dates for this partner in the given month
        busy_dates = list(
            BusyDay.objects.filter(
                partner=partner,
                date__year=year,
                date__month=month,
                service__isnull=True,  # Partner-level busy days
            ).values_list('date', flat=True)
        )

        # Also get service-level busy days (for machinery partners)
        service_busy = list(
            BusyDay.objects.filter(
                partner=partner,
                date__year=year,
                date__month=month,
                service__isnull=False,
            ).values_list('date', 'service_id')
        )

        return Response({
            "year": year,
            "month": month,
            "busy_dates": [d.isoformat() for d in busy_dates],
            "service_busy_dates": [
                {"date": d.isoformat(), "service_id": sid}
                for d, sid in service_busy
            ],
        })


class ToggleBusyDayView(APIView):
    """
    POST /api/v1/availability/toggle-day/
    Body: { "date": "2026-08-20", "reason": "private job" }

    Toggles a date busy/free for the logged-in partner.
    - If BusyDay exists for that date → DELETE it (mark free)
    - If not → CREATE it (mark busy)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            partner = request.user.partner_profile
        except PartnerProfile.DoesNotExist:
            return Response(
                {"error": "You are not registered as a partner."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = ToggleBusyDaySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_date = serializer.validated_data['date']
        reason = serializer.validated_data.get('reason', '')
        service_id = serializer.validated_data.get('service_id')

        # Don't allow marking past dates
        if target_date < timezone.now().date():
            return Response(
                {"error": "Cannot modify past dates."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve service if provided
        service = None
        entity_type = BusyDay.EntityType.PARTNER
        if service_id:
            service = get_object_or_404(
                Service, pk=service_id, partner=partner,
            )
            entity_type = BusyDay.EntityType.SERVICE

        # Toggle: if exists → delete (free), if not → create (busy)
        existing = BusyDay.objects.filter(
            partner=partner,
            service=service,
            date=target_date,
        ).first()

        if existing:
            # Don't allow removing system-created busy days (from bookings)
            if existing.marked_by == BusyDay.MarkedBy.SYSTEM:
                return Response(
                    {
                        "error": "This date is busy due to an active Farmo booking. "
                                 "Cancel the booking to free this date.",
                        "is_busy": True,
                        "locked": True,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            existing.delete()
            return Response({
                "date": target_date.isoformat(),
                "is_busy": False,
                "message": "Date marked as free.",
            })
        else:
            BusyDay.objects.create(
                partner=partner,
                service=service,
                entity_type=entity_type,
                date=target_date,
                marked_by=BusyDay.MarkedBy.SELF,
                marked_by_user=request.user,
                reason=reason,
            )
            return Response({
                "date": target_date.isoformat(),
                "is_busy": True,
                "message": "Date marked as busy.",
            }, status=status.HTTP_201_CREATED)


class PartnerCalendarView(APIView):
    """
    GET /api/v1/availability/<partner_id>/calendar/?month=8&year=2026

    Public view: returns a partner's busy dates for a given month.
    Used by customers and agents to check availability.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, partner_id):
        partner = get_object_or_404(PartnerProfile, pk=partner_id)

        today = timezone.now().date()
        year = int(request.query_params.get('year', today.year))
        month = int(request.query_params.get('month', today.month))

        if not (1 <= month <= 12) or year < 2020:
            return Response(
                {"error": "Invalid month or year."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        busy_dates = list(
            BusyDay.objects.filter(
                partner=partner,
                date__year=year,
                date__month=month,
            ).values_list('date', flat=True)
        )

        return Response({
            "partner_id": partner.id,
            "partner_phone": partner.user.phone_number,
            "year": year,
            "month": month,
            "busy_dates": [d.isoformat() for d in busy_dates],
        })
