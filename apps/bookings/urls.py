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
    # Instant Booking Views
    InstantBookingCreateView,
    InstantBookingStatusView,
    ProviderInstantBookingListView,
    ProviderInstantBookingAcceptView,
    ProviderInstantBookingDeclineView,
)

app_name = 'bookings'

urlpatterns = [
    # Customer Routes
    path('', CustomerBookingListView.as_view(), name='customer-booking-list'),
    path('<str:booking_id>/', CustomerBookingDetailView.as_view(), name='customer-booking-detail'),
    path('<str:booking_id>/cancel/', CustomerBookingCancelView.as_view(), name='customer-booking-cancel'),
    
    # Instant Booking – Customer
    path('instant/', InstantBookingCreateView.as_view(), name='instant-booking-create'),
    path('instant/<str:booking_id>/status/', InstantBookingStatusView.as_view(), name='instant-booking-status'),

    # Provider Routes
    path('provider/list/', ProviderBookingListView.as_view(), name='provider-booking-list'),
    path('provider/<str:booking_id>/', ProviderBookingDetailView.as_view(), name='provider-booking-detail'),
    path('provider/<str:booking_id>/action/', ProviderBookingActionView.as_view(), name='provider-booking-action'),
    path('provider/<str:booking_id>/cancel/', ProviderBookingCancelView.as_view(), name='provider-booking-cancel'),

    # Instant Booking – Provider
    path('provider/instant/', ProviderInstantBookingListView.as_view(), name='provider-instant-list'),
    path('provider/instant/<str:booking_id>/accept/', ProviderInstantBookingAcceptView.as_view(), name='provider-instant-accept'),
    path('provider/instant/<str:booking_id>/decline/', ProviderInstantBookingDeclineView.as_view(), name='provider-instant-decline'),
]