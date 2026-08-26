# apps/availability/urls.py
from django.urls import path
from .views import MyCalendarView, ToggleBusyDayView, PartnerCalendarView

app_name = 'availability'

urlpatterns = [
    # Worker's own calendar (requires auth)
    path('my-calendar/', MyCalendarView.as_view(), name='my-calendar'),

    # Toggle a date busy/free (requires auth)
    path('toggle-day/', ToggleBusyDayView.as_view(), name='toggle-day'),

    # View any partner's calendar (for customers/agents)
    path('<int:partner_id>/calendar/', PartnerCalendarView.as_view(), name='partner-calendar'),
]
