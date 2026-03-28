from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import authenticate, login as auth_login, logout as auth_logout
from django.contrib import messages

def is_admin(user):
    return user.is_authenticated and user.is_staff

def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('adminpanel:dashboard')
        
    if request.method == 'POST':
        phone_number = request.POST.get('phone_number')
        password = request.POST.get('password')
        
        user = authenticate(request, phone_number=phone_number, password=password)
        
        if user is not None:
            if user.is_staff:
                auth_login(request, user)
                return redirect('adminpanel:dashboard')
            else:
                messages.error(request, "You do not have permission to access the admin panel.")
        else:
            messages.error(request, "Invalid credentials.")
            
    return render(request, 'adminpanel/login.html')

def admin_logout(request):
    auth_logout(request)
    return redirect('adminpanel:login')

@user_passes_test(is_admin, login_url='/api/v1/admin/login/')
def dashboard(request):
    context = {
        'page_title': 'Dashboard'
    }
    return render(request, 'adminpanel/dashboard.html', context)

