from django.urls import path
from .views import SendOTPView, VerifyOTPView, GoogleAuthView, ProfileUpdateView, LanguagePreferenceView

app_name = 'users' 

urlpatterns = [
    # Authentication Routes
    path('auth/send-otp/', SendOTPView.as_view(), name='send-otp'),
    path('auth/verify-otp/', VerifyOTPView.as_view(), name='verify-otp'),
    path('auth/google/', GoogleAuthView.as_view(), name='google-auth'),
    # Profile update (new user onboarding)
    path('profile/', ProfileUpdateView.as_view(), name='profile-update'),
    # Language preference
    path('language/', LanguagePreferenceView.as_view(), name='language-preference'),
]