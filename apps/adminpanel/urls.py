from django.urls import path
from . import views

# This is the namespace registration
app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.admin_login, name='login'),
    path('logout/', views.admin_logout, name='logout'),
    path('partners/', views.partners_list, name='partners'),
    path('bookings/', views.bookings_list, name='bookings'),
]