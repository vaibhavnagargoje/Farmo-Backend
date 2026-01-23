# apps/bookings/serializers.py
from rest_framework import serializers
from django.utils import timezone
from .models import Booking
from services.serializers import ServiceListSerializer
from partners.serializers import PartnerProfileSerializer
from users.serializers import UserSerializer


class BookingListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing bookings.
    """
    service_title = serializers.CharField(source='service.title', read_only=True)
    provider_name = serializers.CharField(source='provider.business_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'status', 'payment_status',
            'service_title', 'provider_name', 'customer_phone',
            'scheduled_date', 'scheduled_time', 'total_amount', 'created_at'
        ]


class BookingDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a booking.
    """
    service = ServiceListSerializer(read_only=True)
    provider = PartnerProfileSerializer(read_only=True)
    customer = UserSerializer(read_only=True)
    cancelled_by = UserSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'status', 'payment_status',
            'customer', 'service', 'provider',
            'scheduled_date', 'scheduled_time',
            'work_started_at', 'work_completed_at',
            'start_job_otp', 'end_job_otp',
            'address', 'lat', 'lng',
            'quantity', 'unit_price', 'total_amount',
            'note', 'cancellation_reason', 'cancelled_by',
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
