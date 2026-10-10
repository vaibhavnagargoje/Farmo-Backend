from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # ── Auth ───────────────────────────────────────────────────────────────
    path('login/', views.panel_login, name='login'),
    path('logout/', views.panel_logout, name='logout'),

    # ── Dashboard ──────────────────────────────────────────────────────────
    path('', views.dashboard, name='dashboard'),

    # ── Map View ──────────────────────────────────────────────────────────
    path('map/', views.map_view, name='map-view'),
    path('map/data/', views.map_data, name='map-data'),
    path('map/message-draft/', views.map_message_draft, name='map-message-draft'),

    # ── New Admin Panel: Users ─────────────────────────────────────────────
    path('manage/users/', views.users_list, name='users-list'),
    path('manage/users/add/', views.add_user, name='add-user'),
    path('manage/users/<uuid:user_id>/', views.user_detail, name='user-detail'),

    # User sub-section update endpoints (POST only)
    path('manage/users/<uuid:user_id>/update-info/', views.update_user_info, name='update-user-info'),
    path('manage/users/<uuid:user_id>/customer-profile/', views.update_customer_profile, name='update-customer-profile'),
    path('manage/users/<uuid:user_id>/location/', views.update_user_location, name='update-user-location'),
    path('manage/users/<uuid:user_id>/partner-profile/', views.update_partner_profile, name='update-partner-profile'),
    path('manage/users/<uuid:user_id>/labor-details/', views.update_labor_details, name='update-labor-details'),
    path('manage/users/<uuid:user_id>/machinery-details/', views.update_machinery_details, name='update-machinery-details'),
    path('manage/users/<uuid:user_id>/transport-details/', views.update_transport_details, name='update-transport-details'),

    # Services (nested under user)
    path('manage/users/<uuid:user_id>/services/add/', views.service_create, name='service-create'),
    path('manage/users/<uuid:user_id>/services/<int:service_id>/edit/', views.service_edit, name='service-edit'),
    path('manage/users/<uuid:user_id>/services/<int:service_id>/images/upload/', views.service_image_upload, name='service-image-upload'),
    path('manage/users/<uuid:user_id>/services/<int:service_id>/images/<int:image_id>/delete/', views.service_image_delete, name='service-image-delete'),

    # ── Calendar / Availability ───────────────────────────────────────────
    path('manage/users/<uuid:user_id>/calendar/', views.agent_worker_calendar, name='worker-calendar'),
    path('manage/users/<uuid:user_id>/calendar/toggle/', views.agent_toggle_busy_day, name='worker-calendar-toggle'),
    path('manage/users/<uuid:user_id>/calendar/booking-action/', views.agent_worker_booking_action, name='worker-calendar-booking-action'),
    path('manage/availability/', views.agent_workers_by_date, name='workers-by-date'),

    # ── Bookings ──────────────────────────────────────────────────────────
    path('bookings/', views.bookings_overview, name='bookings'),
    path('bookings/all/', views.bookings_list, name='bookings-list'),
    path('bookings/instant/', views.bookings_list, name='bookings-instant'),
    path('bookings/scheduled/', views.bookings_list, name='bookings-scheduled'),
    path('bookings/export/', views.bookings_export, name='bookings-export'),

    # Actions on one booking (used by Map View and Bookings pages; POST JSON)
    path('bookings/actions/assign/', views.booking_assign_partner, name='booking-assign'),
    path('bookings/actions/cancel/', views.booking_cancel, name='booking-cancel'),
    path('bookings/actions/complete/', views.booking_complete, name='booking-complete'),
    path('bookings/actions/retry-search/', views.booking_rebroadcast, name='booking-rebroadcast'),
    path('bookings/actions/update-pricing/', views.booking_update_pricing, name='booking-update-pricing'),

    # Quick Book wizard (global slide-over; JSON)
    path('bookings/quick-book/user-search/', views.quick_book_user_search, name='quick-book-user-search'),
    path('bookings/quick-book/categories/', views.quick_book_categories, name='quick-book-categories'),
    path('bookings/quick-book/create/', views.quick_book_create, name='quick-book-create'),

    # Booking detail (catch-all last; ids look like FB-XXXXXXXX / BK-XXXXXXXX)
    path('bookings/<str:booking_id>/', views.booking_detail, name='booking-detail'),
]

