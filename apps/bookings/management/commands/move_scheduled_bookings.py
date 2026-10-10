"""
One-off: move old scheduled bookings into ProviderContact.

Scheduled bookings came from the "Find yourself" flow (the customer called a
provider and said "yes" afterwards). There is one kind of booking now, and
those calls are recorded as direct contacts. Run this once on each server right
after `migrate`:

    python manage.py move_scheduled_bookings --dry-run   # show what would move
    python manage.py move_scheduled_bookings

Old scheduled bookings are recognised by their booking ID: scheduled bookings
were always created as BK-XXXXXXXX, bookings through Farmo as FB-XXXXXXXX.
Each one becomes an AGREED contact with its original date and booking ID, then
the booking is deleted. Running it again skips bookings already moved.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from bookings.models import Booking, ProviderContact

LEGACY_SCHEDULED_PREFIX = 'BK-'


class Command(BaseCommand):
    help = 'Move old scheduled (BK-) bookings into direct provider contacts.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would move without changing anything.')

    def handle(self, *args, dry_run=False, **options):
        scheduled = Booking.objects.filter(
            booking_id__startswith=LEGACY_SCHEDULED_PREFIX,
        ).select_related('service').order_by('created_at')
        total = scheduled.count()
        if not total:
            self.stdout.write(self.style.SUCCESS('No old scheduled bookings to move.'))
            return

        already_moved = set(
            ProviderContact.objects.filter(legacy_booking_id__startswith=LEGACY_SCHEDULED_PREFIX)
            .values_list('legacy_booking_id', flat=True)
        )
        if dry_run:
            self.stdout.write(f'{total} old scheduled booking(s) found; {len(already_moved)} already have a contact.')
            for booking in scheduled:
                self.stdout.write(f'  {booking.booking_id}  {booking.status:<12} {booking.created_at:%Y-%m-%d}')
            self.stdout.write('Dry run: nothing changed.')
            return

        contacts, booking_pks = [], []
        with transaction.atomic():
            for booking in scheduled.select_for_update(of=('self',)):
                booking_pks.append(booking.pk)
                service = booking.service
                provider_id = booking.provider_id or (service.partner_id if service else None)
                if booking.booking_id not in already_moved and provider_id is not None:
                    contacts.append(ProviderContact(
                        customer_id=booking.customer_id,
                        provider_id=provider_id,
                        service_id=booking.service_id,
                        category_id=booking.category_id or (service.category_id if service else None),
                        quantity=booking.quantity,
                        price_unit=booking.price_unit or '',
                        listed_unit_price=booking.unit_price,
                        address=booking.address or '',
                        lat=booking.lat,
                        lng=booking.lng,
                        note=booking.note or '',
                        outcome=ProviderContact.Outcome.AGREED,
                        responded_at=booking.created_at,
                        legacy_booking_id=booking.booking_id,
                        created_at=booking.created_at,
                    ))
            # bulk_create skips save signals, so providers get no "found you" push for old bookings.
            ProviderContact.objects.bulk_create(contacts, batch_size=500)
            # Offers cascade; system busy days keep the date blocked (BusyDay.booking is SET_NULL).
            Booking.objects.filter(pk__in=booking_pks).delete()

        moved, skipped = len(contacts), len(booking_pks) - len(contacts)
        self.stdout.write(self.style.SUCCESS(
            f'Moved {moved} old scheduled booking(s) into direct contacts'
            + (f'; {skipped} removed without a new contact (already moved or no provider).' if skipped else '.')
        ))
