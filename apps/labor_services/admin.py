from django.contrib import admin
from .models import LaborCategory, LaborServiceType, LaborDetails

@admin.register(LaborCategory)
class LaborCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)

@admin.register(LaborServiceType)
class LaborServiceTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'slug', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    list_filter = ('category', 'is_active')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'category__name')

@admin.register(LaborDetails)
class LaborDetailsAdmin(admin.ModelAdmin):
    list_display = ('partner', 'daily_wage_estimate', 'is_migrant_worker', 'display_skills')
    list_filter = ('is_migrant_worker',)
    search_fields = ('partner__user__phone_number', 'service_types__name')
    filter_horizontal = ('service_types',)

    def display_skills(self, obj):
        skills = obj.service_types.all()
        if not skills:
            return "-"
        return ", ".join([s.get_name('en') or s.name for s in skills])
    display_skills.short_description = "Service Types"
