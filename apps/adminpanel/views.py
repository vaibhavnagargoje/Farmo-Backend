from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages
from django.core.cache import cache
from django.http import HttpResponseForbidden

from apps.users.models import User
from partners.models import PartnerProfile
from services.models import Service
from bookings.models import Booking

MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_TIME = 600 # 10 minutes

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    return request.META.get('REMOTE_ADDR')

def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

def admin_login(request):
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        return redirect('adminpanel:dashboard')

    if request.method == 'POST':
        ip = get_client_ip(request)
        cache_key = f'adminpanel_login_attempts_{ip}'
        attempts = cache.get(cache_key, 0)

        if attempts >= MAX_LOGIN_ATTEMPTS:
            messages.error(request, 'Too many failed attempts. Please try again later.')
            return render(request, 'adminpanel/login.html')

        phone_number = request.POST.get('phone_number')
        password = request.POST.get('password')

        user = authenticate(request, phone_number=phone_number, password=password)

        if user is not None:
            if user.is_staff or user.is_superuser:
                auth_login(request, user)
                cache.delete(cache_key) # clear on success
                return redirect('adminpanel:dashboard')
            else:
                attempts += 1
                cache.set(cache_key, attempts, LOCKOUT_TIME)
                messages.error(request, 'You do not have permission to access the admin panel.')
        else:
            attempts += 1
            cache.set(cache_key, attempts, LOCKOUT_TIME)
            messages.error(request, f'Invalid credentials. Attempt {attempts} of {MAX_LOGIN_ATTEMPTS}.')

    return render(request, 'adminpanel/login.html')

def admin_logout(request):
    auth_logout(request)
    return redirect('adminpanel:login')

@user_passes_test(is_admin, login_url='/api/v1/admin/login/')
def dashboard(request):
    context = {
        'page_title': 'Dashboard',
        'total_users': User.objects.filter(role=User.Role.CUSTOMER).count(),
        'active_partners': PartnerProfile.objects.filter(is_verified=True).count(),
        'total_bookings': Booking.objects.count(),
        'pending_partners': PartnerProfile.objects.filter(is_kyc_submitted=True, is_verified=False).count(),
        'rejected_partners': PartnerProfile.objects.exclude(rejected_reason='').exclude(rejected_reason__isnull=True).count(),
        'pending_services': Service.objects.filter(status=Service.Status.PENDING).count(),
        'inactive_services': Service.objects.filter(status__in=[Service.Status.DRAFT, Service.Status.HIDDEN]).count(),
        'labor_count': PartnerProfile.objects.filter(partner_type=PartnerProfile.PartnerType.LABOR).count(),
        'recent_bookings': Booking.objects.select_related('customer', 'service').order_by('-created_at')[:5]
    }
    return render(request, 'adminpanel/dashboard.html', context)

@user_passes_test(is_admin, login_url='/api/v1/admin/login/')
def partners_list(request):
    list_type = request.GET.get('type', 'all')
    partners_query = PartnerProfile.objects.select_related('user')
    
    if list_type == 'pending':
        partners_query = partners_query.filter(is_kyc_submitted=True, is_verified=False)
    elif list_type == 'rejected':
        partners_query = partners_query.exclude(rejected_reason='').exclude(rejected_reason__isnull=True)
        
    context = {
        'page_title': 'Partners Management',
        'partners': partners_query.order_by('-created_at')[:100],
        'list_type': list_type
    }
    return render(request, 'adminpanel/partners.html', context)

@user_passes_test(is_admin, login_url='/api/v1/admin/login/')
def bookings_list(request):
    context = {
        'page_title': 'Bookings',
        'bookings': Booking.objects.select_related('customer', 'service').order_by('-created_at')[:100]
    }
    return render(request, 'adminpanel/bookings.html', context)

from django.contrib.admin import site
original_django_admin_login = site.login

def rate_limited_django_admin_login(request, *args, **kwargs):
    if request.method == 'POST':
        ip = get_client_ip(request)
        cache_key = f'django_admin_login_attempts_{ip}'
        attempts = cache.get(cache_key, 0)

        if attempts >= MAX_LOGIN_ATTEMPTS:
            return HttpResponseForbidden('Too many failing login attempts. Please try again later.')

        response = original_django_admin_login(request, *args, **kwargs)

        if response.status_code == 200:
            attempts += 1
            cache.set(cache_key, attempts, LOCKOUT_TIME)
        else:
            cache.delete(cache_key)

        return response

    return original_django_admin_login(request, *args, **kwargs)
