# apps/bookings/serializers.py
from decimal import Decimal

from rest_framework import serializers
from django.utils import timezone
from .dispatch import BookingError, active_booking, create_booking, create_provider_contact
from .models import Booking, BookingOffer, ProviderContact
from services.serializers import ServiceListSerializer
from services.models import Category, Service
from partners.serializers import PartnerProfileSerializer
from partners.models import PartnerProfile
from users.serializers import UserSerializer

MAX_QUANTITY = Decimal("10000")

# Deprecated: every booking is now a Farmo booking. Older app versions still
# read booking_type to pick icons and labels (and treat a missing value as
# "scheduled"), so responses keep sending this constant for one release.
LEGACY_BOOKING_TYPE = 'INSTANT'


def quantity_input_field(**kwargs):
    """Work quantity sent by the app: decimals allowed (3.5 acres), up to 2 places."""
    return serializers.DecimalField(
        max_digits=8, decimal_places=2, min_value=Decimal("0.01"), max_value=MAX_QUANTITY, **kwargs,
    )


def quantity_output_field(**kwargs):
    """Quantity as a JSON number (3.5, 5) rather than the string "3.50"."""
    return serializers.DecimalField(
        max_digits=8, decimal_places=2, coerce_to_string=False, read_only=True, **kwargs,
    )


def legacy_booking_type_field():
    return serializers.SerializerMethodField(help_text="Deprecated; always INSTANT.")


class BookingListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing bookings.
    """
    service_title = serializers.SerializerMethodField()
    provider_name = serializers.CharField(source='provider.user.customer_profile.full_name', read_only=True, default=None)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_name_translations = serializers.JSONField(source='category.name_translations', read_only=True, default=dict)
    quantity = quantity_output_field()
    booking_type = legacy_booking_type_field()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'order_number', 'booking_type', 'status', 'payment_status',
            'service_title', 'category_name', 'category_name_translations', 'provider_name', 'customer_phone',
            'scheduled_date', 'scheduled_time', 'quantity', 'price_unit', 'unit_price', 'discount_amount', 'total_amount', 'expires_at',
            'address', 'lat', 'lng', 'note', 'cancellation_reason',
            'broadcast_count', 'assigned_at', 'created_at',
            'otp_mode_snapshot',
        ]

    def get_booking_type(self, obj):
        return LEGACY_BOOKING_TYPE

    def get_service_title(self, obj):
        if obj.service:
            return obj.service.title
        if obj.category:
            return obj.category.name
        return "Unknown"


class BookingDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a booking.
    """
    service = ServiceListSerializer(read_only=True)
    provider = PartnerProfileSerializer(read_only=True)
    customer = UserSerializer(read_only=True)
    cancelled_by = UserSerializer(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_name_translations = serializers.JSONField(source='category.name_translations', read_only=True, default=dict)
    quantity = quantity_output_field()
    booking_type = legacy_booking_type_field()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'order_number', 'booking_type', 'status', 'payment_status',
            'customer', 'service', 'provider', 'category_name', 'category_name_translations',
            'scheduled_date', 'scheduled_time', 'expires_at',
            'broadcast_count', 'current_broadcast_radius', 'assigned_at',
            'work_started_at', 'work_completed_at',
            'start_job_otp', 'end_job_otp', 'job_otp', 'otp_mode_snapshot',
            'address', 'lat', 'lng',
            'quantity', 'price_unit', 'unit_price', 'discount_amount', 'total_amount',
            'note', 'cancellation_reason', 'cancelled_by',
            'created_at', 'updated_at'
        ]

    def get_booking_type(self, obj):
        return LEGACY_BOOKING_TYPE

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        effective_mode = instance.otp_mode_snapshot or 'DUAL'

        # Determine viewer role
        is_provider = (
            request and request.user and
            hasattr(request.user, 'partner_profile') and
            request.user.partner_profile == instance.provider
        )

        if effective_mode == 'SINGLE':
            # --- SINGLE OTP mode ---
            # Customer: always sees job_otp (so they can share it)
            # Provider: job_otp is hidden (they enter what the customer gives them)
            if is_provider:
                data['job_otp'] = '****' if data.get('job_otp') else None
            # Neither role needs start/end OTPs in SINGLE mode
            data['start_job_otp'] = None
            data['end_job_otp'] = None
        else:
            # --- DUAL OTP mode (existing behaviour) ---
            # job_otp not applicable — mask it
            data['job_otp'] = None
            if is_provider:
                # Provider viewing — hide start OTP, show end OTP
                data['start_job_otp'] = '****' if data.get('start_job_otp') else None
            else:
                # Customer viewing — show start OTP always
                # Show end OTP only when job is IN_PROGRESS
                if instance.status != Booking.Status.IN_PROGRESS:
                    data['end_job_otp'] = '****' if data.get('end_job_otp') else None

        return data


class BookingStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating booking status (Provider actions).
    Providers accept a booking through its offer, so only start/complete remain here.
    """
    action = serializers.ChoiceField(choices=['start', 'complete'])
    otp = serializers.CharField(max_length=6, required=False)

    def validate(self, attrs):
        action = attrs.get('action')
        booking = self.context.get('booking')

        # Determine effective mode from the booking's snapshot (protects mid-flow switches)
        effective_mode = booking.otp_mode_snapshot or 'DUAL'

        if action == 'start':
            if effective_mode == 'SINGLE':
                raise serializers.ValidationError(
                    "'start' action is not applicable in Single OTP mode. "
                    "Use 'complete' with the job OTP instead."
                )
            if booking.status != Booking.Status.CONFIRMED:
                raise serializers.ValidationError("Can only start CONFIRMED bookings.")
            if attrs.get('otp') != booking.start_job_otp:
                raise serializers.ValidationError({"otp": "Invalid start OTP."})

        if action == 'complete':
            if effective_mode == 'SINGLE':
                # In SINGLE mode: complete directly from CONFIRMED (skip IN_PROGRESS)
                if booking.status not in (Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS):
                    raise serializers.ValidationError(
                        "Can only complete a CONFIRMED booking in Single OTP mode."
                    )
                if attrs.get('otp') != booking.job_otp:
                    raise serializers.ValidationError({"otp": "Invalid OTP."})
            else:
                # DUAL mode: must be IN_PROGRESS and use end OTP
                if booking.status != Booking.Status.IN_PROGRESS:
                    raise serializers.ValidationError("Can only complete IN_PROGRESS bookings.")
                if attrs.get('otp') != booking.end_job_otp:
                    raise serializers.ValidationError({"otp": "Invalid completion OTP."})

        return attrs


class BookingCancelSerializer(serializers.Serializer):
    """
    Serializer for cancelling a booking.
    """
    reason = serializers.CharField(required=True, min_length=10)

    def validate(self, attrs):
        booking = self.context.get('booking')

        if booking.status in [Booking.Status.COMPLETED, Booking.Status.CANCELLED]:
            raise serializers.ValidationError("Cannot cancel a completed or already cancelled booking.")

        if booking.status == Booking.Status.IN_PROGRESS:
            raise serializers.ValidationError("Cannot cancel a booking that is already in progress. Contact support.")

        return attrs


class BookingCreateSerializer(serializers.Serializer):
    """
    Serializer for creating a booking through Farmo ("Book through Farmo").
    Prices the job for the location and broadcasts it to nearby providers.
    """
    category_id = serializers.IntegerField()
    quantity = quantity_input_field()
    price_unit = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Deprecated and ignored: the unit is always taken from the resolved pricing zone."
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    scheduled_date = serializers.DateField(required=False, allow_null=True)
    scheduled_time = serializers.TimeField(required=False, allow_null=True)

    def validate_scheduled_date(self, value):
        if value and value < timezone.localdate():
            raise serializers.ValidationError("Scheduled date cannot be in the past.")
        return value

    def validate_lat(self, value):
        """Coerce lat to 6 decimal places so it fits the model's DecimalField(max_digits=9)."""
        return round(float(value), 6)

    def validate_lng(self, value):
        """Coerce lng to 6 decimal places so it fits the model's DecimalField(max_digits=9)."""
        return round(float(value), 6)

    def validate_category_id(self, value):
        try:
            category = Category.objects.get(id=value, is_active=True)
        except Category.DoesNotExist:
            raise serializers.ValidationError("Category not found or not active.")
        if not category.instant_enabled:
            raise serializers.ValidationError("Booking through Farmo is not enabled for this category.")
        return value

    def validate(self, attrs):
        """Check if user already has an active booking in the SAME category."""
        existing = active_booking(self.context['request'].user, attrs['category_id'])
        if existing:
            raise serializers.ValidationError({
                "active_booking_id": existing.booking_id,
                "message": "You already have an active order in this category. Cancel it or wait for it to expire.",
            })
        return attrs

    def create(self, validated_data):
        # Pricing (zone → default zone → category) and the provider broadcast
        # live in bookings.dispatch so Quick Book in the admin panel shares them.
        try:
            booking, _providers_notified = create_booking(
                customer=self.context['request'].user,
                category=Category.objects.get(id=validated_data['category_id']),
                lat=validated_data['lat'],
                lng=validated_data['lng'],
                address=validated_data['address'],
                quantity=validated_data['quantity'],
                note=validated_data.get('note', ''),
                scheduled_date=validated_data.get('scheduled_date'),
                scheduled_time=validated_data.get('scheduled_time'),
            )
        except BookingError as exc:
            raise serializers.ValidationError(str(exc))
        return booking


class BookingOfferSerializer(serializers.ModelSerializer):
    """
    Serializer for showing pending BookingOffers to providers.
    Flattens booking details so the frontend has everything it needs.
    """
    booking_id = serializers.CharField(source='booking.booking_id', read_only=True)
    booking_type = legacy_booking_type_field()
    booking_status = serializers.CharField(source='booking.status', read_only=True)
    category_name = serializers.SerializerMethodField()
    service_title = serializers.SerializerMethodField()
    customer_phone = serializers.CharField(source='booking.customer.phone_number', read_only=True)
    address = serializers.CharField(source='booking.address', read_only=True)
    lat = serializers.DecimalField(source='booking.lat', max_digits=9, decimal_places=6, read_only=True)
    lng = serializers.DecimalField(source='booking.lng', max_digits=9, decimal_places=6, read_only=True)
    quantity = quantity_output_field(source='booking.quantity')
    price_unit = serializers.CharField(source='booking.price_unit', read_only=True)
    unit_price = serializers.DecimalField(source='booking.unit_price', max_digits=10, decimal_places=2, read_only=True)
    discount_amount = serializers.DecimalField(source='booking.discount_amount', max_digits=10, decimal_places=2, read_only=True)
    total_amount = serializers.DecimalField(source='booking.total_amount', max_digits=10, decimal_places=2, read_only=True)
    note = serializers.CharField(source='booking.note', read_only=True, default='')
    expires_at = serializers.DateTimeField(source='booking.expires_at', read_only=True)
    order_number = serializers.CharField(source='booking.order_number', read_only=True)
    created_at = serializers.DateTimeField(source='booking.created_at', read_only=True)

    class Meta:
        model = BookingOffer
        fields = [
            'id', 'booking_id', 'booking_type', 'booking_status', 'order_number',
            'category_name', 'service_title', 'customer_phone',
            'address', 'lat', 'lng',
            'quantity', 'price_unit', 'unit_price', 'discount_amount', 'total_amount',
            'note', 'expires_at', 'created_at',
            'status', 'distance_km', 'notified_at', 'response_deadline',
        ]

    def get_booking_type(self, obj):
        return LEGACY_BOOKING_TYPE

    def get_category_name(self, obj):
        if obj.booking.category:
            return obj.booking.category.name
        return None

    def get_service_title(self, obj):
        if obj.booking.service:
            return obj.booking.service.title
        if obj.booking.category:
            return obj.booking.category.name
        return "Unknown"


# --- Direct provider contacts ("Find yourself") ---

class ProviderContactCreateSerializer(serializers.Serializer):
    """
    A customer is about to call (or has called) a provider from a listing.
    Older app versions send the same payload to POST /bookings/ after the call.
    """
    service_id = serializers.IntegerField()
    quantity = quantity_input_field(required=False, allow_null=True)
    price_unit = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=20)
    note = serializers.CharField(required=False, allow_null=True, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_null=True, allow_blank=True, default="")
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)
    outcome = serializers.ChoiceField(
        choices=ProviderContact.Outcome.choices, required=False, default=ProviderContact.Outcome.CALLED,
    )

    def validate_service_id(self, value):
        if not Service.objects.filter(id=value, status=Service.Status.ACTIVE).exists():
            raise serializers.ValidationError("Service not found or not available.")
        return value

    def validate(self, attrs):
        lat, lng = attrs.get('lat'), attrs.get('lng')
        # The app sends 0, 0 when it has no location.
        if lat is None or lng is None or (not lat and not lng):
            attrs['lat'] = attrs['lng'] = None
        else:
            attrs['lat'], attrs['lng'] = round(float(lat), 6), round(float(lng), 6)
        return attrs

    def create(self, validated_data):
        service = Service.objects.select_related('price_unit').get(id=validated_data['service_id'])
        try:
            return create_provider_contact(
                customer=self.context['request'].user,
                service=service,
                quantity=validated_data.get('quantity'),
                price_unit=validated_data.get('price_unit') or '',
                note=validated_data.get('note') or '',
                address=validated_data.get('address') or '',
                lat=validated_data['lat'],
                lng=validated_data['lng'],
                outcome=validated_data['outcome'],
            )
        except BookingError as exc:
            raise serializers.ValidationError(str(exc))


class ProviderContactOutcomeSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=[
        ProviderContact.Outcome.AGREED, ProviderContact.Outcome.NOT_AGREED,
    ])


class ProviderContactSerializer(serializers.ModelSerializer):
    """The customer's own view of a contact."""
    class Meta:
        model = ProviderContact
        fields = ['id', 'outcome', 'created_at', 'responded_at']


class PartnerContactSerializer(serializers.ModelSerializer):
    """A farmer who found this partner on Farmo, as the partner sees it."""
    customer_name = serializers.CharField(source='customer.customer_profile.full_name', read_only=True, default='')
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    service_title = serializers.CharField(source='service.title', read_only=True, default=None)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    category_name_translations = serializers.JSONField(source='category.name_translations', read_only=True, default=dict)
    quantity = quantity_output_field()

    class Meta:
        model = ProviderContact
        fields = [
            'id', 'customer_name', 'customer_phone',
            'service_title', 'category_name', 'category_name_translations',
            'quantity', 'price_unit', 'address', 'note',
            'outcome', 'created_at', 'responded_at',
        ]
