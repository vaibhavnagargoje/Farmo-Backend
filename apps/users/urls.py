from django.urls import path
from .views import SendOTPView, VerifyOTPView, ProfileUpdateView

app_name = 'users' 

urlpatterns = [
    # OTP Authentication Routes
    path('auth/send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('auth/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    # Profile update (new user onboarding)
    path('profile/', ProfileUpdateView.as_view(), name='profile-update'),
]