from django.urls import path
from .views import UserLocationView

app_name = 'locations'

urlpatterns = [
    # User location management (authenticated)
    path('user-location/', UserLocationView.as_view(), name='user-location'),
]
