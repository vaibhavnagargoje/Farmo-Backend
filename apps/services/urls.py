# apps/services/urls.py
from django.urls import path
from .views import (
    CategoryListView,
    ServiceListView,
    ServiceDetailView,
    PartnerServiceListView,
    PartnerServiceDetailView,
    ServiceImageUploadView,
    ServiceImageDeleteView
)

app_name = 'services'

urlpatterns = [
    # Public Routes (Customers Browsing)
    path('categories/', CategoryListView.as_view(), name='category-list'),
    path('', ServiceListView.as_view(), name='service-list'),
    path('<int:id>/', ServiceDetailView.as_view(), name='service-detail'),
    
    # Partner Routes (Manage Own Services)
    path('my/', PartnerServiceListView.as_view(), name='partner-service-list'),
    path('my/<int:service_id>/', PartnerServiceDetailView.as_view(), name='partner-service-detail'),
    path('my/<int:service_id>/images/', ServiceImageUploadView.as_view(), name='service-image-upload'),
    path('my/<int:service_id>/images/<int:image_id>/', ServiceImageDeleteView.as_view(), name='service-image-delete'),
]