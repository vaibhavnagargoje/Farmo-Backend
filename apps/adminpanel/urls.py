from django.urls import path
from . import views

# This is the namespace registration
app_name = 'adminpanel'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('login/', views.admin_login, name='login'),
    path('logout/', views.admin_logout, name='logout'),
]