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
    BookingCreateView,
    BookingStatusView,
    ProviderOfferListView,
    ProviderOfferAcceptView,
    ProviderOfferDeclineView,
    ProviderContactCreateView,
    ProviderContactOutcomeView,
    ProviderContactListView,
    AppSettingsView,
)

app_name = 'bookings'

# The "instant" paths are kept as they are: released app versions call them.
urlpatterns = [
    # Public settings endpoint (OTP mode toggle, etc.)
    path('settings/', AppSettingsView.as_view(), name='app-settings'),

    # Booking through Farmo (must be before <str:booking_id> catch-all)
    path('instant/', BookingCreateView.as_view(), name='booking-create'),
    path('instant/<str:booking_id>/status/', BookingStatusView.as_view(), name='booking-status'),

    # Direct provider contacts ("Find yourself")
    path('contacts/', ProviderContactCreateView.as_view(), name='provider-contact-create'),
    path('contacts/<int:pk>/outcome/', ProviderContactOutcomeView.as_view(), name='provider-contact-outcome'),

    # Customer Routes
    path('', CustomerBookingListView.as_view(), name='customer-booking-list'),
    path('<str:booking_id>/cancel/', CustomerBookingCancelView.as_view(), name='customer-booking-cancel'),

    # Provider offer and contact routes (must be before provider/<str:booking_id>/ catch-all)
    path('provider/instant-requests/', ProviderOfferListView.as_view(), name='provider-offer-list'),
    path('provider/instant-requests/<int:pk>/accept/', ProviderOfferAcceptView.as_view(), name='provider-offer-accept'),
    path('provider/instant-requests/<int:pk>/decline/', ProviderOfferDeclineView.as_view(), name='provider-offer-decline'),
    path('provider/contacts/', ProviderContactListView.as_view(), name='provider-contact-list'),

    # Provider Routes (catch-all <str:booking_id> patterns last)
    path('provider/list/', ProviderBookingListView.as_view(), name='provider-booking-list'),
    path('provider/<str:booking_id>/', ProviderBookingDetailView.as_view(), name='provider-booking-detail'),
    path('provider/<str:booking_id>/action/', ProviderBookingActionView.as_view(), name='provider-booking-action'),
    path('provider/<str:booking_id>/cancel/', ProviderBookingCancelView.as_view(), name='provider-booking-cancel'),

    # Customer detail (catch-all last)
    path('<str:booking_id>/', CustomerBookingDetailView.as_view(), name='customer-booking-detail'),
]
