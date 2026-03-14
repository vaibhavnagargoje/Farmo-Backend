from django.core.management.base import BaseCommand
from django.utils import timezone
from bookings.models import Booking

class Command(BaseCommand):
    help = 'Force expires all Instant Bookings that have passed their expires_at time.'

    def handle(self, *args, **options):
        now = timezone.now()
        # Find stuck master bookings
        stale_bookings = Booking.objects.filter(
            status=Booking.Status.SEARCHING,
            booking_type=Booking.BookingType.INSTANT,
            expires_at__lt=now
        )
        
        count = 0
        for booking in stale_bookings:
            booking.status = Booking.Status.EXPIRED
            booking.save() # THIS LINE triggers the cascade that cancels the 5 provider leads!
            count += 1
            
        self.stdout.write(self.style.SUCCESS(f'Successfully expired {count} bookings and their provider leads.'))
