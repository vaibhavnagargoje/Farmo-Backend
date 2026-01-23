# apps/services/serializers.py
from rest_framework import serializers
from .models import Category, Service, ServiceImage
from partners.serializers import PartnerProfileSerializer


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Service Categories.
    """
    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'icon', 'is_active']
        read_only_fields = ['id', 'slug']


class ServiceImageSerializer(serializers.ModelSerializer):
    """
    Serializer for Service Images.
    """
    class Meta:
        model = ServiceImage
        fields = ['id', 'image', 'is_thumbnail']
        read_only_fields = ['id']


class ServiceListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for listing services (e.g., search results).
    """
    category_name = serializers.CharField(source='category.name', read_only=True)
    partner_name = serializers.CharField(source='partner.business_name', read_only=True)
    partner_rating = serializers.DecimalField(source='partner.rating', max_digits=3, decimal_places=2, read_only=True)
    thumbnail = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'price', 'price_unit', 'category_name',
            'partner_name', 'partner_rating', 'is_available', 'thumbnail',
            'location_lat', 'location_lng', 'service_radius_km'
        ]

    def get_thumbnail(self, obj):
        thumbnail = obj.images.filter(is_thumbnail=True).first()
        if thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(thumbnail.image.url)
        return None


class ServiceDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a single service.
    """
    category = CategorySerializer(read_only=True)
    partner = PartnerProfileSerializer(read_only=True)
    images = ServiceImageSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'description', 'price', 'price_unit', 'min_order_qty',
            'category', 'partner', 'status', 'is_available',
            'location_lat', 'location_lng', 'service_radius_km',
            'specifications', 'images', 'created_at', 'updated_at'
        ]


class ServiceCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for Partners to create a new Service.
    """
    images = serializers.ListField(
        child=serializers.ImageField(),
        write_only=True,
        required=False
    )

    class Meta:
        model = Service
        fields = [
            'category', 'title', 'description', 'price', 'price_unit', 'min_order_qty',
            'location_lat', 'location_lng', 'service_radius_km', 'specifications', 'images'
        ]

    def create(self, validated_data):
        images_data = validated_data.pop('images', [])
        
        # Get the partner profile from the authenticated user
        user = self.context['request'].user
        partner = user.partner_profile
        
        # Create the service
        service = Service.objects.create(partner=partner, **validated_data)
        
        # Create images
        for i, image in enumerate(images_data):
            ServiceImage.objects.create(
                service=service,
                image=image,
                is_thumbnail=(i == 0)  # First image is thumbnail
            )
        
        return service


class ServiceUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for Partners to update their Service.
    """
    class Meta:
        model = Service
        fields = [
            'title', 'description', 'price', 'price_unit', 'min_order_qty',
            'is_available', 'location_lat', 'location_lng', 'service_radius_km', 'specifications'
        ]
