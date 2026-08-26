from django.urls import path
from .views import (
    LaborCategoryListView,
    NearbyLaborsByTypeView,
    LaborServiceTypeListView
)

app_name = 'labor_services'

urlpatterns = [
    path('categories/', LaborCategoryListView.as_view(), name='category-list'),
    path('service-types/', LaborServiceTypeListView.as_view(), name='service-type-list'),
    path('nearby/', NearbyLaborsByTypeView.as_view(), name='nearby-labors'),
]
