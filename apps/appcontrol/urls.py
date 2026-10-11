from django.urls import path

from .views import AppConfigView

app_name = 'appcontrol'

urlpatterns = [
    path('config/', AppConfigView.as_view(), name='config'),
]
