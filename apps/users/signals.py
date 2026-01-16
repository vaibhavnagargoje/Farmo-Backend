# apps/users/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import User, CustomerProfile

@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        # If user is a CUSTOMER, create CustomerProfile
        if instance.role == User.Role.CUSTOMER:
            CustomerProfile.objects.create(user=instance)
        
        # Note: We usually DON'T auto-create PartnerProfile 
        # because Partners need to fill a specific registration form
        # with business name, etc., via API.