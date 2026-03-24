from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, CustomerProfile

class UserAdmin(BaseUserAdmin):
    # Use phone_number for ordering and display
    ordering = ['phone_number']
    list_display = ['phone_number', 'email', 'role', 'preferred_language', 'is_staff', 'is_active']
    search_fields = ['phone_number', 'email']
    list_filter = ('role', 'preferred_language', 'is_active', 'is_staff')
    
    # Organize the fields in the admin detail view
    fieldsets = (
        (None, {'fields': ('phone_number', 'password')}),
        ('Personal info', {'fields': ('email',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
        ('Role & Language', {'fields': ('role', 'preferred_language')}),
    )
    
    # Configuration for the "Add User" page
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('phone_number', 'email', 'password1', 'password2', 'role', 'preferred_language', 'is_staff', 'is_active'),
        }),
    )

admin.site.register(User, UserAdmin)
admin.site.register(CustomerProfile)

