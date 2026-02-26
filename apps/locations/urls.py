from django.urls import path
from .views import StateListView, DistrictListView, TahsilListView,VillageListView, UserLocationView

app_name = 'locations'

urlpatterns = [
    # Location hierarchy (public)
    path('states/', StateListView.as_view(), name='state-list'),
    path('districts/', DistrictListView.as_view(), name='district-list'),
    path('tahsils/', TahsilListView.as_view(), name='tahsil-list'),
    path('villages/', VillageListView.as_view(), name='village-list'),

    # User location management (authenticated)
    path('user-location/', UserLocationView.as_view(), name='user-location'),
]
