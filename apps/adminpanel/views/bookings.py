"""Existing agent booking acceptance and rejection endpoints."""

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from bookings.models import Booking, InstantBookingRequest
from partners.models import PartnerProfile
from users.models import User

from ..permissions import is_agent


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
