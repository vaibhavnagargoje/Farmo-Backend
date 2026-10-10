from django.core.management.base import BaseCommand
from django.utils import timezone
from bookings.models import Booking

class Command(BaseCommand):
    help = 'Force expires all bookings whose provider search passed its expires_at time.'

    def handle(self, *args, **options):
        now = timezone.now()
        # Find stuck master bookings
        stale_bookings = Booking.objects.filter(
            status=Booking.Status.SEARCHING,
            expires_at__lt=now
        )
        
        count = 0
        for booking in stale_bookings:
            booking.status = Booking.Status.EXPIRED
            booking.save() # THIS LINE triggers the cascade that expires the pending provider offers!
            count += 1
            
        self.stdout.write(self.style.SUCCESS(f'Successfully expired {count} bookings and their provider offers.'))
