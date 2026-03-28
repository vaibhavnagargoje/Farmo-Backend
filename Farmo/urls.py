"""
URL configuration for Farmo project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static

from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
)

# Apply rate-limit override to Core Django Admin
from apps.adminpanel.views import rate_limited_django_admin_login
from django.contrib.admin import site
site.login = rate_limited_django_admin_login

urlpatterns = [
    path('admin/', admin.site.urls),


    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    # API V1 Routes
    # --- API VERSION 1 ---

    # Users App (Authentication & User Management)
    path('api/v1/users/', include('users.urls', namespace='users')),

    # Locations App (State/District/Tahsil & User Location)
    path('api/v1/locations/', include('locations.urls', namespace='locations')),
    
    # Partners App (Partner Registration & Management)
    path('api/v1/partners/', include('partners.urls', namespace='partners')),
    
    # Services App (Service Listings & Categories)
    path('api/v1/services/', include('services.urls', namespace='services')),
    
    # Bookings App (Customer & Provider Bookings)
    path('api/v1/bookings/', include('bookings.urls', namespace='bookings')),

    # Notifications App (FCM & Alerts)
    path('api/v1/notifications/', include('notifications.urls', namespace='notifications')),
    
    # Search App
    path('api/v1/search/', include('search.urls', namespace='search')),

    # Admin Panel App
    path('api/v1/admin/', include('adminpanel.urls', namespace='adminpanel')),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Include django_browser_reload URLs only in DEBUG mode
    urlpatterns += [
        path("__reload__/", include("django_browser_reload.urls")),
        
    ]