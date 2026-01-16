from django.urls import path
from .views import SendOTPView, VerifyOTPView

app_name = 'users' 

urlpatterns = [
    # OTP Authentication Routes
    path('auth/send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('auth/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
]