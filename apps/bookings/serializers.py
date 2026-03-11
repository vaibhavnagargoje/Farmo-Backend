# apps/bookings/serializers.py
from rest_framework import serializers
from django.utils import timezone
from django.db.models import FloatField, Value, F, ExpressionWrapper
from django.db.models.functions import ACos, Cos, Radians, Sin
from .models import Booking, InstantBookingRequest
from services.serializers import ServiceListSerializer
from services.models import Category, Service
from partners.serializers import PartnerProfileSerializer
from partners.models import PartnerProfile
from users.serializers import UserSerializer


class BookingListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing bookings.
    """
    service_title = serializers.SerializerMethodField()
    provider_name = serializers.CharField(source='provider.user.customer_profile.full_name', read_only=True, default=None)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'order_number', 'booking_type', 'status', 'payment_status',
            'service_title', 'category_name', 'provider_name', 'customer_phone',
            'scheduled_date', 'scheduled_time', 'quantity', 'price_unit', 'unit_price', 'total_amount', 'expires_at',
            'address', 'lat', 'lng', 'note', 'cancellation_reason',
            'broadcast_count', 'assigned_at', 'created_at'
        ]

    def get_service_title(self, obj):
        if obj.service:
            return obj.service.title
        if obj.category:
            return f"{obj.category.name} (Instant)"
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

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'order_number', 'booking_type', 'status', 'payment_status',
            'customer', 'service', 'provider', 'category_name',
            'scheduled_date', 'scheduled_time', 'expires_at',
            'broadcast_count', 'current_broadcast_radius', 'assigned_at',
            'work_started_at', 'work_completed_at',
            'start_job_otp', 'end_job_otp',
            'address', 'lat', 'lng',
            'quantity', 'price_unit', 'unit_price', 'total_amount',
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


class InstantBookingCreateSerializer(serializers.Serializer):
    """
    Serializer for creating an Instant (Quick) Booking.
    Finds nearby providers, computes average price, creates broadcast requests.
    """
    category_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField()
    lat = serializers.FloatField()
    lng = serializers.FloatField()

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
            raise serializers.ValidationError("Instant booking is not enabled for this category.")
        return value

    def validate(self, attrs):
        """Check if user already has an active instant booking."""
        user = self.context['request'].user
        active_booking = Booking.objects.filter(
            customer=user,
            booking_type=Booking.BookingType.INSTANT,
            status__in=[
                Booking.Status.SEARCHING,
                Booking.Status.CONFIRMED,
                Booking.Status.IN_PROGRESS,
            ],
        ).first()
        if active_booking:
            raise serializers.ValidationError({
                "active_booking_id": active_booking.booking_id,
                "message": "You already have an active order. Cancel it or wait for it to expire.",
            })
        return attrs

    def _find_nearby_services(self, category, user_lat, user_lng, radius_km):
        """
        Find active services within radius using Haversine formula.
        Uses partner's UserLocation for coordinates.
        Returns queryset annotated with distance.
        """
        queryset = Service.objects.filter(
            category=category,
            status=Service.Status.ACTIVE,
            is_available=True,
            partner__is_available=True,
            partner__is_verified=True,
        ).exclude(
            partner__user__location__isnull=True
        ).exclude(
            partner__user__location__latitude__isnull=True
        ).exclude(
            partner__user__location__longitude__isnull=True
        )

        queryset = queryset.annotate(
            distance=ExpressionWrapper(
                Value(6371.0) * ACos(
                    Cos(Radians(Value(float(user_lat), output_field=FloatField()))) *
                    Cos(Radians(F('partner__user__location__latitude'))) *
                    Cos(Radians(F('partner__user__location__longitude')) - Radians(Value(float(user_lng), output_field=FloatField()))) +
                    Sin(Radians(Value(float(user_lat), output_field=FloatField()))) *
                    Sin(Radians(F('partner__user__location__latitude')))
                ),
                output_field=FloatField()
            )
        ).filter(distance__lte=radius_km).order_by('distance')

        return queryset

    def create(self, validated_data):
        user = self.context['request'].user
        category = Category.objects.get(id=validated_data['category_id'])
        user_lat = validated_data['lat']
        user_lng = validated_data['lng']
        quantity = validated_data['quantity']
        radius_km = category.instant_search_radius_km

        # Use admin-set instant price from the category
        unit_price = round(float(category.instant_price), 2)
        if unit_price <= 0:
            raise serializers.ValidationError(
                "Instant booking price is not configured for this category."
            )
        price_unit = category.instant_price_unit

        # Find nearby services for provider broadcast
        nearby_services = self._find_nearby_services(
            category, user_lat, user_lng, radius_km
        )

        # Create the booking
        booking = Booking.objects.create(
            booking_type=Booking.BookingType.INSTANT,
            customer=user,
            category=category,
            status=Booking.Status.SEARCHING,
            address=validated_data['address'],
            lat=user_lat,
            lng=user_lng,
            quantity=quantity,
            price_unit=price_unit,
            unit_price=unit_price,
            total_amount=round(unit_price * quantity, 2),
            note=validated_data.get('note', ''),
        )

        # Find distinct providers from nearby services and create broadcast requests
        # Use distinct partners to avoid sending multiple requests to the same provider
        seen_providers = set()
        broadcast_count = 0
        for svc in nearby_services.select_related('partner'):
            if svc.partner_id not in seen_providers:
                seen_providers.add(svc.partner_id)
                InstantBookingRequest.objects.create(
                    booking=booking,
                    provider=svc.partner,
                    broadcast_round=1,
                    distance_km=round(svc.distance, 2) if svc.distance else None,
                    response_deadline=booking.expires_at,
                )
                broadcast_count += 1

        booking.broadcast_count = 1
        booking.current_broadcast_radius = radius_km
        booking.save(update_fields=['broadcast_count', 'current_broadcast_radius'])

        return booking


class InstantBookingRequestSerializer(serializers.ModelSerializer):
    """
    Serializer for showing pending InstantBookingRequests to providers.
    Flattens booking details so the frontend has everything it needs.
    """
    booking_id = serializers.CharField(source='booking.booking_id', read_only=True)
    booking_type = serializers.CharField(source='booking.booking_type', read_only=True)
    booking_status = serializers.CharField(source='booking.status', read_only=True)
    category_name = serializers.SerializerMethodField()
    service_title = serializers.SerializerMethodField()
    customer_phone = serializers.CharField(source='booking.customer.phone_number', read_only=True)
    address = serializers.CharField(source='booking.address', read_only=True)
    lat = serializers.DecimalField(source='booking.lat', max_digits=9, decimal_places=6, read_only=True)
    lng = serializers.DecimalField(source='booking.lng', max_digits=9, decimal_places=6, read_only=True)
    quantity = serializers.IntegerField(source='booking.quantity', read_only=True)
    price_unit = serializers.CharField(source='booking.price_unit', read_only=True)
    unit_price = serializers.DecimalField(source='booking.unit_price', max_digits=10, decimal_places=2, read_only=True)
    total_amount = serializers.DecimalField(source='booking.total_amount', max_digits=10, decimal_places=2, read_only=True)
    note = serializers.CharField(source='booking.note', read_only=True, default='')
    expires_at = serializers.DateTimeField(source='booking.expires_at', read_only=True)
    order_number = serializers.CharField(source='booking.order_number', read_only=True)
    created_at = serializers.DateTimeField(source='booking.created_at', read_only=True)

    class Meta:
        model = InstantBookingRequest
        fields = [
            'id', 'booking_id', 'booking_type', 'booking_status', 'order_number',
            'category_name', 'service_title', 'customer_phone',
            'address', 'lat', 'lng',
            'quantity', 'price_unit', 'unit_price', 'total_amount',
            'note', 'expires_at', 'created_at',
            'status', 'distance_km', 'notified_at', 'response_deadline',
        ]

    def get_category_name(self, obj):
        if obj.booking.category:
            return obj.booking.category.name
        return None

    def get_service_title(self, obj):
        if obj.booking.service:
            return obj.booking.service.title
        if obj.booking.category:
            return f"{obj.booking.category.name} (Instant)"
        return "Unknown"