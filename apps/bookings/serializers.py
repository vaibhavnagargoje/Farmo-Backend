# apps/bookings/serializers.py
from rest_framework import serializers
from django.utils import timezone
from .models import Booking, InstantBookingRequest
from services.serializers import ServiceListSerializer
from services.models import Category
from partners.serializers import PartnerProfileSerializer
from users.serializers import UserSerializer


class BookingListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing bookings.
    """
    service_title = serializers.SerializerMethodField()
    provider_name = serializers.CharField(source='provider.business_name', read_only=True, default=None)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'booking_type', 'status', 'payment_status',
            'service_title', 'category_name', 'provider_name', 'customer_phone',
            'scheduled_date', 'scheduled_time', 'total_amount', 'expires_at', 'created_at'
        ]

    def get_service_title(self, obj):
        if obj.service:
            return obj.service.title
        if obj.category:
            return f"{obj.category.name} (Instant)"
        return "Unknown"


class InstantBookingRequestSerializer(serializers.ModelSerializer):
    """Serializer for instant booking broadcast requests."""
    provider_name = serializers.CharField(source='provider.business_name', read_only=True)
    provider_rating = serializers.DecimalField(source='provider.rating', max_digits=3, decimal_places=2, read_only=True)

    class Meta:
        model = InstantBookingRequest
        fields = [
            'id', 'provider', 'provider_name', 'provider_rating',
            'status', 'distance_km', 'notified_at', 'responded_at'
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a booking.
    """
    service = ServiceListSerializer(read_only=True)
    provider = PartnerProfileSerializer(read_only=True)
    customer = UserSerializer(read_only=True)
    cancelled_by = UserSerializer(read_only=True)
    instant_requests = InstantBookingRequestSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'booking_type', 'status', 'payment_status',
            'customer', 'service', 'provider', 'category_name',
            'scheduled_date', 'scheduled_time', 'expires_at',
            'work_started_at', 'work_completed_at',
            'start_job_otp', 'end_job_otp',
            'address', 'lat', 'lng',
            'quantity', 'unit_price', 'total_amount',
            'note', 'cancellation_reason', 'cancelled_by',
            'instant_requests',
            'created_at', 'updated_at'
        ]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        
        # Hide OTPs based on who is viewing
        if request and request.user:
            # Customer sees start_job_otp (gives to provider)
            # Provider sees end_job_otp (gives to customer)
            if hasattr(request.user, 'partner_profile') and request.user.partner_profile == instance.provider:
                # Provider viewing - hide start_job_otp, show end_job_otp
                data['start_job_otp'] = '****' if data['start_job_otp'] else None
            else:
                # Customer viewing - hide end_job_otp, show start_job_otp
                data['end_job_otp'] = '****' if data['end_job_otp'] else None
        
        return data


class BookingCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for Customers to create a new Booking.
    """
    service_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = Booking
        fields = [
            'service_id', 'scheduled_date', 'scheduled_time',
            'address', 'lat', 'lng', 'quantity', 'note'
        ]

    def validate_service_id(self, value):
        from services.models import Service
        try:
            service = Service.objects.get(id=value, status=Service.Status.ACTIVE, is_available=True)
        except Service.DoesNotExist:
            raise serializers.ValidationError("Service not found or not available.")
        return value

    def validate_scheduled_date(self, value):
        if value < timezone.now().date():
            raise serializers.ValidationError("Scheduled date cannot be in the past.")
        return value

    def validate(self, attrs):
        from services.models import Service
        service = Service.objects.get(id=attrs['service_id'])
        quantity = attrs.get('quantity', 1)
        
        # Check minimum order quantity
        if quantity < service.min_order_qty:
            raise serializers.ValidationError({
                "quantity": f"Minimum order quantity is {service.min_order_qty}."
            })
        
        return attrs

    def create(self, validated_data):
        from services.models import Service
        
        service_id = validated_data.pop('service_id')
        service = Service.objects.get(id=service_id)
        
        # Create booking with snapshot pricing
        booking = Booking.objects.create(
            customer=self.context['request'].user,
            service=service,
            provider=service.partner,
            unit_price=service.price,
            total_amount=service.price * validated_data.get('quantity', 1),
            **validated_data
        )
        
        return booking


class BookingStatusUpdateSerializer(serializers.Serializer):
    """
    Serializer for updating booking status (Provider actions).
    """
    action = serializers.ChoiceField(choices=['accept', 'reject', 'start', 'complete'])
    otp = serializers.CharField(max_length=6, required=False)
    rejection_reason = serializers.CharField(required=False)

    def validate(self, attrs):
        action = attrs.get('action')
        booking = self.context.get('booking')
        
        if action == 'accept' and booking.status != Booking.Status.PENDING:
            raise serializers.ValidationError("Can only accept PENDING bookings.")
        
        if action == 'reject':
            if booking.status != Booking.Status.PENDING:
                raise serializers.ValidationError("Can only reject PENDING bookings.")
            if not attrs.get('rejection_reason'):
                raise serializers.ValidationError({"rejection_reason": "Required when rejecting."})
        
        if action == 'start':
            if booking.status != Booking.Status.CONFIRMED:
                raise serializers.ValidationError("Can only start CONFIRMED bookings.")
            if attrs.get('otp') != booking.start_job_otp:
                raise serializers.ValidationError({"otp": "Invalid start OTP."})
        
        if action == 'complete':
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


# ─── INSTANT BOOKING SERIALIZERS ───

class InstantBookingCreateSerializer(serializers.Serializer):
    """
    Serializer for creating an instant (quick) booking.
    Customer provides: category_slug + location. Price comes from Category (admin-set).
    """
    category_slug = serializers.SlugField()
    address = serializers.CharField()
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)
    quantity = serializers.IntegerField(default=1, min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default='')

    def validate_category_slug(self, value):
        try:
            category = Category.objects.get(slug=value, is_active=True)
        except Category.DoesNotExist:
            raise serializers.ValidationError("Category not found or not active.")
        
        if not category.instant_enabled:
            raise serializers.ValidationError("Instant booking is not available for this category.")
        
        if category.instant_price <= 0:
            raise serializers.ValidationError("Instant booking price not set for this category. Contact admin.")
        
        return value

    def create(self, validated_data):
        category = Category.objects.get(slug=validated_data['category_slug'])
        quantity = validated_data.get('quantity', 1)
        
        booking = Booking.objects.create(
            booking_type=Booking.BookingType.INSTANT,
            customer=self.context['request'].user,
            category=category,
            service=None,
            provider=None,
            status=Booking.Status.SEARCHING,
            address=validated_data['address'],
            lat=validated_data['lat'],
            lng=validated_data['lng'],
            quantity=quantity,
            unit_price=category.instant_price,
            total_amount=category.instant_price * quantity,
            note=validated_data.get('note', ''),
        )
        
        return booking


class InstantBookingAcceptSerializer(serializers.Serializer):
    """
    Serializer for a provider to accept an instant booking request.
    First-come-first-serve: only works if the booking is still SEARCHING.
    """
    
    def validate(self, attrs):
        booking = self.context.get('booking')
        provider = self.context.get('provider')
        
        # Check booking is still searching
        if booking.status != Booking.Status.SEARCHING:
            raise serializers.ValidationError(
                "This booking is no longer available. Another provider may have accepted it."
            )
        
        # Check booking hasn't expired
        if booking.is_expired:
            raise serializers.ValidationError("This booking has expired.")
        
        # Check this provider has a pending request for this booking
        try:
            request_obj = InstantBookingRequest.objects.get(
                booking=booking, provider=provider, status=InstantBookingRequest.RequestStatus.PENDING
            )
        except InstantBookingRequest.DoesNotExist:
            raise serializers.ValidationError("You don't have a pending request for this booking.")
        
        attrs['request_obj'] = request_obj
        return attrs