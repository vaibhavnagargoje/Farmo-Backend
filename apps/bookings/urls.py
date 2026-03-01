# apps/bookings/urls.py
from django.urls import path
from .views import (
    CustomerBookingListView,
    CustomerBookingDetailView,
    CustomerBookingCancelView,
    ProviderBookingListView,
    ProviderBookingDetailView,
    ProviderBookingActionView,
    ProviderBookingCancelView,
    InstantBookingCreateView,
    InstantBookingStatusView,
)

app_name = 'bookings'

urlpatterns = [
    # Instant Booking Routes (must be before <str:booking_id> catch-all)
    path('instant/', InstantBookingCreateView.as_view(), name='instant-booking-create'),
    path('instant/<str:booking_id>/status/', InstantBookingStatusView.as_view(), name='instant-booking-status'),

    # Customer Routes
    path('', CustomerBookingListView.as_view(), name='customer-booking-list'),
    path('<str:booking_id>/', CustomerBookingDetailView.as_view(), name='customer-booking-detail'),
    path('<str:booking_id>/cancel/', CustomerBookingCancelView.as_view(), name='customer-booking-cancel'),
    
    # Provider Routes
    path('provider/list/', ProviderBookingListView.as_view(), name='provider-booking-list'),
    path('provider/<str:booking_id>/', ProviderBookingDetailView.as_view(), name='provider-booking-detail'),
    path('provider/<str:booking_id>/action/', ProviderBookingActionView.as_view(), name='provider-booking-action'),
    path('provider/<str:booking_id>/cancel/', ProviderBookingCancelView.as_view(), name='provider-booking-cancel'),
]
