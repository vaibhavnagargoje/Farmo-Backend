from django.urls import path
from .views import (
    LaborCategoryListView,
    NearbyLaborsByTypeView,
    LaborServiceTypeListView,
    LaborPriceUnitsView,
)

app_name = 'labor_services'

urlpatterns = [
    path('categories/', LaborCategoryListView.as_view(), name='category-list'),
    path('service-types/', LaborServiceTypeListView.as_view(), name='service-type-list'),
    path('price-units/', LaborPriceUnitsView.as_view(), name='price-unit-list'),
    path('nearby/', NearbyLaborsByTypeView.as_view(), name='nearby-labors'),
]
