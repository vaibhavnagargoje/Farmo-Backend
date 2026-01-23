from django.contrib import admin
from .models import Booking

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    # What columns to show in the list
    list_display = (
        'booking_id', 
        'status', 
        'customer', 
        'provider', 
        'service', 
        'scheduled_date', 
        'total_amount', 
        'payment_status'
    )
    
    # Sidebar filters to quickly find specific bookings
    list_filter = (
        'status', 
        'payment_status', 
        'scheduled_date', 
        'created_at'
    )
    
    # Search functionality
    search_fields = (
        'booking_id', 
        'customer__phone_number', 
        'customer__first_name', 
        'provider__business_name', 
        'service__title'
    )
    
    # Fields that shouldn't be edited manually by admins (system generated)
    readonly_fields = (
        'booking_id', 
        'total_amount', 
        'start_job_otp', 
        'end_job_otp', 
        'created_at', 
        'updated_at'
    )

    # Organize the form into logical sections
    fieldsets = (
        ('Overview', {
            'fields': ('booking_id', 'status', 'payment_status')
        }),
        ('Parties Involved', {
            'fields': ('customer', 'provider', 'service')
        }),
        ('Schedule & Location', {
            'fields': ('scheduled_date', 'scheduled_time', 'address', 'lat', 'lng')
        }),
        ('Financials', {
            'fields': ('quantity', 'unit_price', 'total_amount')
        }),
        ('Execution', {
             'description': "Tracking when the work actually happened",
            'fields': ('start_job_otp', 'end_job_otp', 'work_started_at', 'work_completed_at')
        }),
        ('Meta Data', {
            'fields': ('note', 'cancellation_reason', 'cancelled_by', 'created_at', 'updated_at'),
            'classes': ('collapse',) # Hides this section by default to keep UI clean
        }),
    )
