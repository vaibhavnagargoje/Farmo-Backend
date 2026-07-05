from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
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

    # ── Legacy VLE flow (preserved) ────────────────────────────────────────
    path('register/user/', views.register_user, name='register-user'),
    path('register/<uuid:user_id>/next/', views.registration_next, name='registration-next'),
    path('register/<uuid:user_id>/create-worker-profile/', views.create_worker_profile, name='create-worker-profile'),
    path('register/<uuid:user_id>/worker-details/', views.worker_details, name='worker-details'),
    path('register/<uuid:user_id>/list-machinery/', views.create_machinery_profile_placeholder, name='list-machinery'),
]