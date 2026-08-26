# apps/partners/urls.py
from django.urls import path
from .views import (
    PartnerStatusView,
    PartnerRegistrationView,
    PartnerOnboardOrAddServiceView,
    PartnerProfileView,
    PartnerPublicView,
    PartnerDashboardView,
    LaborDetailsView,
    NearbyLaborsView,
)

app_name = 'partners'

urlpatterns = [
    # Master Labor Skills List (multi-language) - DEPRECATED, moved to labor_services
    # path('skills/', LaborSkillListView.as_view(), name='skills-list'),

    # Partner Status Check (for onboarding flow)
    path('status/', PartnerStatusView.as_view(), name='status'),
    
    # Partner Registration & Profile Management
    path('register/', PartnerRegistrationView.as_view(), name='register'),
    path('onboard-or-add-service/', PartnerOnboardOrAddServiceView.as_view(), name='onboard-or-add-service'),
    path('profile/', PartnerProfileView.as_view(), name='profile'),
    path('dashboard/', PartnerDashboardView.as_view(), name='dashboard'),
    
    # Public Partner View (for customers)
    path('<int:id>/', PartnerPublicView.as_view(), name='public-profile'),
    
    # Labor Details (view/edit for LABOR partners)
    path('labor-details/', LaborDetailsView.as_view(), name='labor-details'),
    
    # Nearby Labors (public, location-based)
    path('nearby-labors/', NearbyLaborsView.as_view(), name='nearby-labors'),
]
