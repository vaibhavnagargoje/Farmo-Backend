from django.contrib import admin
from .models import LaborCategory, LaborServiceType, LaborDetails, LaborServiceOffering, LaborPriceUnit

@admin.register(LaborPriceUnit)
class LaborPriceUnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    search_fields = ('name',)

class LaborServiceOfferingInline(admin.TabularInline):
    model = LaborServiceOffering
    extra = 1
    autocomplete_fields = ('service_type', 'price_unit')
    fields = ('service_type', 'price', 'price_unit', 'note')


@admin.register(LaborCategory)
class LaborCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

@admin.register(LaborServiceType)
class LaborServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'default_price_unit', 'slug', 'is_active', 'order')
    list_editable = ('is_active', 'order', 'default_price_unit')
    list_filter = ('category', 'is_active', 'default_price_unit')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'category__name')

@admin.register(LaborDetails)
class LaborDetailsAdmin(admin.ModelAdmin):
    list_display = ('partner', 'daily_wage_estimate', 'is_migrant_worker', 'display_skills')
    list_filter = ('is_migrant_worker',)
    search_fields = ('partner__user__phone_number',)
    inlines = [LaborServiceOfferingInline]

    def display_skills(self, obj):
        offerings = obj.offerings.select_related('service_type', 'price_unit').all()
        if not offerings:
            return "-"
        return ", ".join([
            f"{o.service_type.name} (₹{o.price}/{o.price_unit.name})"
            for o in offerings
        ])
    display_skills.short_description = "Service Offerings"


@admin.register(LaborServiceOffering)
class LaborServiceOfferingAdmin(admin.ModelAdmin):
    list_display = ('labor_details', 'service_type', 'price', 'price_unit', 'note')
    list_filter = ('price_unit', 'service_type__category')
    search_fields = ('labor_details__partner__user__phone_number', 'service_type__name')
    autocomplete_fields = ('labor_details', 'service_type', 'price_unit')
