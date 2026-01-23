# apps/partners/urls.py
from django.urls import path
from .views import (
    PartnerRegistrationView,
    PartnerProfileView,
    PartnerPublicView,
    PartnerDashboardView
)

app_name = 'partners'

urlpatterns = [
    # Partner Registration & Profile Management
    path('register/', PartnerRegistrationView.as_view(), name='register'),
    path('profile/', PartnerProfileView.as_view(), name='profile'),
    path('dashboard/', PartnerDashboardView.as_view(), name='dashboard'),
    
    # Public Partner View (for customers)
    path('<int:id>/', PartnerPublicView.as_view(), name='public-profile'),
]