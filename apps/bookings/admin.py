from django.contrib import admin
from django.utils.html import format_html
from .models import Booking, InstantBookingRequest


class InstantBookingRequestInline(admin.TabularInline):
    """
    Shows all provider requests for an instant booking inside the Booking form.
    """
    model = InstantBookingRequest
    extra = 0
    readonly_fields = ('provider', 'status', 'distance_km', 'notified_at', 'responded_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # System creates these, not admin


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'booking_id', 
        'booking_type_badge',
        'status', 
        'customer', 
        'provider', 
        'service_or_category',
        'scheduled_date', 
        'total_amount', 
        'payment_status'
    )
    
    list_filter = (
        'booking_type',
        'status', 
        'payment_status', 
        'scheduled_date', 
        'created_at'
    )
    
    search_fields = (
        'booking_id', 
        'customer__phone_number', 
        'customer__first_name', 
        'provider__business_name', 
        'service__title',
        'category__name'
    )
    
    readonly_fields = (
        'booking_id', 
        'booking_type',
        'total_amount', 
        'start_job_otp', 
        'end_job_otp', 
        'expires_at',
        'created_at', 
        'updated_at'
    )

    inlines = [InstantBookingRequestInline]

    fieldsets = (
        ('Overview', {
            'fields': ('booking_id', 'booking_type', 'status', 'payment_status')
        }),
        ('Parties Involved', {
            'fields': ('customer', 'provider', 'service', 'category')
        }),
        ('Schedule & Location', {
            'fields': ('scheduled_date', 'scheduled_time', 'expires_at', 'address', 'lat', 'lng')
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
            'classes': ('collapse',)
        }),
    )

    @admin.display(description='Type')
    def booking_type_badge(self, obj):
        if obj.booking_type == Booking.BookingType.INSTANT:
            return format_html('<span style="background:#f59e0b;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">⚡ INSTANT</span>')
        return format_html('<span style="background:#3b82f6;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:bold;">📅 SCHEDULED</span>')

    @admin.display(description='Service / Category')
    def service_or_category(self, obj):
        if obj.service:
            return obj.service.title
        if obj.category:
            return f"[Instant] {obj.category.name}"
        return '-'


@admin.register(InstantBookingRequest)
class InstantBookingRequestAdmin(admin.ModelAdmin):
    list_display = ('booking', 'provider', 'status', 'distance_km', 'notified_at', 'responded_at')
    list_filter = ('status',)
    search_fields = ('booking__booking_id', 'provider__business_name')
    readonly_fields = ('booking', 'provider', 'notified_at')
