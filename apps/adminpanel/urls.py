from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('register/user/', views.register_user, name='register-user'),
    path('register/<uuid:user_id>/next/', views.registration_next, name='registration-next'),
    path(
        'register/<uuid:user_id>/create-worker-profile/',
        views.create_worker_profile,
        name='create-worker-profile',
    ),
    path(
        'register/<uuid:user_id>/worker-details/',
        views.worker_details,
        name='worker-details',
    ),
    path(
        'register/<uuid:user_id>/list-machinery/',
        views.create_machinery_profile_placeholder,
        name='list-machinery',
    ),
]