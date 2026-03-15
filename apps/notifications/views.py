from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from .models import DeviceToken, Notification
from .serializers import DeviceTokenSerializer, NotificationSerializer

class RegisterDeviceTokenView(generics.CreateAPIView):
    """
    POST /api/notifications/register-device/
    Registers a Firebase Cloud Messaging token for the logged-in user.
    """
    queryset = DeviceToken.objects.all()
    serializer_class = DeviceTokenSerializer
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        device_token = serializer.save()
        return Response({'message': 'Device token registered successfully', 'token': device_token.token}, status=status.HTTP_201_CREATED)


class NotificationListView(generics.ListAPIView):
    """
    GET /api/notifications/
    Lists all notifications for the logged in user.
    """
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)


class MarkNotificationReadView(APIView):
    """
    POST /api/notifications/<id>/read/
    Marks a notification as read.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            notification = Notification.objects.get(pk=pk, user=request.user)
            notification.is_read = True
            notification.save()
            return Response({'message': 'Notification marked as read'})
        except Notification.DoesNotExist:
            return Response({'message': 'Notification not found'}, status=status.HTTP_404_NOT_FOUND)


class MarkAllNotificationsReadView(APIView):
    """
    POST /api/notifications/mark-all-read/
    Marks all unread notifications as read for the logged-in user.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'message': f'{updated} notifications marked as read'})
