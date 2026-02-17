from django.contrib import admin
from .models import Category, Service, ServiceImage

class ServiceImageInline(admin.TabularInline):
    """
    Allows adding images directly inside the Service page.
    """
    model = ServiceImage
    extra = 1  # Shows one empty slot by default

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'instant_enabled', 'instant_price', 'instant_price_unit')
    prepopulated_fields = {'slug': ('name',)}
    list_filter = ('is_active', 'instant_enabled')
    search_fields = ('name',)
    list_editable = ('instant_price', 'instant_enabled')

    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'slug', 'icon', 'is_active')
        }),
        ('Instant Booking Settings', {
            'description': 'Configure pricing and behavior for instant (quick) bookings. Price is set here by admin.',
            'fields': (
                'instant_enabled', 'instant_price', 'instant_price_unit',
                'instant_timeout_minutes', 'instant_search_radius_km'
            )
        }),
    )

@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = (
        'title', 
        'partner', 
        'category', 
        'price', 
        'price_unit', 
        'status', 
        'is_available'
    )
    list_filter = ('status', 'is_available', 'category', 'price_unit')
    search_fields = ('title', 'partner__business_name')
    readonly_fields = ('created_at', 'updated_at')
    
    # This puts the image uploader inside the Service form
    inlines = [ServiceImageInline]
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('partner', 'category', 'title', 'description')
        }),
        ('Pricing & Availability', {
            'fields': ('price', 'price_unit', 'min_order_qty', 'status', 'is_available')
        }),
        ('Location', {
            'fields': ('location_lat', 'location_lng', 'service_radius_km')
        }),
        ('Technical', {
            'fields': ('specifications', 'created_at', 'updated_at')
        }),
    )

@admin.register(ServiceImage)
class ServiceImageAdmin(admin.ModelAdmin):
    list_display = ('service', 'is_thumbnail')
