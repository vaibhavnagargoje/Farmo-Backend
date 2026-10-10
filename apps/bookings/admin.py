from django.contrib import admin
from django.utils import timezone
from .models import Booking, BookingOffer, ProviderContact


class BookingOfferInline(admin.TabularInline):
    """
    Shows all provider offers for a booking inside the Booking form.
    Status is editable so admin can accept a specific provider (triggers cascade).
    """
    model = BookingOffer
    extra = 0
    readonly_fields = ('provider', 'distance_km', 'notified_at', 'responded_at')
    fields = ('provider', 'status', 'distance_km', 'notified_at', 'responded_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False  # System creates these, not admin


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'booking_id',
        'status',
        'customer',
        'provider',
        'service_or_category',
        'scheduled_date',
        'total_amount',
        'payment_status'
    )

    list_filter = (
        'status',
        'payment_status',
        'scheduled_date',
        'created_at'
    )

    search_fields = (
        'booking_id',
        'customer__phone_number',
        'provider__user__phone_number',
        'service__title',
        'category__name'
    )

    readonly_fields = (
        'booking_id',
        'total_amount',
        'start_job_otp',
        'end_job_otp',
        'expires_at',
        'created_at',
        'updated_at',
        'accepted_by_agent',
        'price_updated_by',
        'price_updated_at',
    )

    inlines = [BookingOfferInline]

    fieldsets = (
        ('Overview', {
            'fields': ('booking_id', 'status', 'payment_status')
        }),
        ('Parties Involved', {
            'fields': ('customer', 'provider', 'accepted_by_agent', 'service', 'category')
        }),
        ('Schedule & Location', {
            'fields': ('scheduled_date', 'scheduled_time', 'expires_at', 'address', 'lat', 'lng')
        }),
        ('Financials', {
            'description': "Total = quantity × unit price − discount (recalculated on save)",
            'fields': ('quantity', 'unit_price', 'discount_amount', 'total_amount', 'price_updated_by', 'price_updated_at')
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

    def save_model(self, request, obj, form, change):
        if {'quantity', 'unit_price', 'discount_amount'} & set(form.changed_data):
            obj.recalculate_total()
            if change:
                obj.price_updated_by = request.user
                obj.price_updated_at = timezone.now()
        super().save_model(request, obj, form, change)

    @admin.display(description='Service / Category')
    def service_or_category(self, obj):
        if obj.service:
            return obj.service.title
        if obj.category:
            return obj.category.name
        return '-'


@admin.register(BookingOffer)
class BookingOfferAdmin(admin.ModelAdmin):
    list_display = ('booking', 'provider', 'status', 'distance_km', 'notified_at', 'responded_at')
    list_filter = ('status',)
    search_fields = ('booking__booking_id', 'provider__user__phone_number')
    readonly_fields = ('booking', 'provider', 'notified_at')


@admin.register(ProviderContact)
class ProviderContactAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'customer', 'provider', 'service', 'category', 'quantity', 'price_unit', 'outcome')
    list_filter = ('outcome', 'category', 'created_at')
    search_fields = ('customer__phone_number', 'provider__user__phone_number', 'provider__business_name', 'service__title', 'legacy_booking_id')
    readonly_fields = ('customer', 'provider', 'service', 'category', 'created_at', 'responded_at', 'legacy_booking_id')
    list_select_related = ('customer', 'provider', 'service', 'category')
