from django.urls import path
from .views import RegisterDeviceTokenView, NotificationListView, MarkNotificationReadView, MarkAllNotificationsReadView

app_name = 'notifications'

urlpatterns = [
    path('register-device/', RegisterDeviceTokenView.as_view(), name='register-device'),
    path('', NotificationListView.as_view(), name='notification-list'),
    path('mark-all-read/', MarkAllNotificationsReadView.as_view(), name='notification-mark-all-read'),
    path('<int:pk>/read/', MarkNotificationReadView.as_view(), name='notification-read'),
]