from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # ── Auth ───────────────────────────────────────────────────────────────
    path('login/', views.panel_login, name='login'),
    path('logout/', views.panel_logout, name='logout'),

    # ── Dashboard ──────────────────────────────────────────────────────────
    path('', views.dashboard, name='dashboard'),

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
]