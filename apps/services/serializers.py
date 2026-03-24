# apps/services/serializers.py
from rest_framework import serializers
from .models import Category, Service, ServiceImage
from partners.serializers import PartnerProfileSerializer


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Service Categories.
    Supports: ?lang=mr for translated names, ?lat=&lng= for zone pricing.
    """
    name = serializers.SerializerMethodField()
    instant_price = serializers.SerializerMethodField()
    instant_price_unit = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'name_translations', 'slug', 'icon', 'is_active', 'instant_price', 'instant_price_unit', 'instant_enabled']
        read_only_fields = ['id', 'slug']

    def _get_lang(self):
        """Get language from ?lang= query param, default 'en'."""
        request = self.context.get('request')
        if request:
            return request.query_params.get('lang', 'en')
        return 'en'

    def get_name(self, obj):
        """Return translated name if available for requested language."""
        lang = self._get_lang()
        if lang != 'en' and obj.name_translations:
            translated = obj.name_translations.get(lang)
            if translated:
                return translated
        return obj.name

    def _resolve_zone_price(self, obj):
        """Resolve zone price once and cache on the serializer instance."""
        cache_key = f'_zone_cache_{obj.pk}'
        if not hasattr(self, cache_key):
            request = self.context.get('request')
            result = None
            if request:
                lat = request.query_params.get('lat')
                lng = request.query_params.get('lng')
                if lat and lng:
                    try:
                        from locations.pricing import resolve_instant_price
                        price, unit, zone_name = resolve_instant_price(obj, float(lat), float(lng))
                        result = (price, unit)
                    except (ValueError, TypeError):
                        pass
            setattr(self, cache_key, result)
        return getattr(self, cache_key)

    def get_instant_price(self, obj):
        resolved = self._resolve_zone_price(obj)
        if resolved:
            return str(resolved[0])
        return str(obj.instant_price)

    def get_instant_price_unit(self, obj):
        resolved = self._resolve_zone_price(obj)
        if resolved:
            return resolved[1]
        return obj.instant_price_unit


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
    category_name = serializers.SerializerMethodField()
    partner_name = serializers.CharField(source='partner.user.customer_profile.full_name', read_only=True, default='')
    partner_rating = serializers.DecimalField(source='partner.rating', max_digits=3, decimal_places=2, read_only=True)
    partner_profile_picture = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    partner_location = serializers.SerializerMethodField()
    images = ServiceImageSerializer(many=True, read_only=True)

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'description', 'price', 'price_unit', 'category', 'category_name',
            'partner_name', 'partner_rating', 'partner_profile_picture', 'status', 'is_available', 'thumbnail',
            'partner_location', 'service_radius_km', 'images'
        ]

    def get_thumbnail(self, obj):
        thumbnail = obj.images.filter(is_thumbnail=True).first()
        if thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(thumbnail.image.url)
        return None

    def get_category_name(self, obj):
        request = self.context.get('request')
        lang = request.query_params.get('lang', 'en') if request else 'en'
        if lang != 'en' and obj.category and obj.category.name_translations:
            translated = obj.category.name_translations.get(lang)
            if translated:
                return translated
        return obj.category.name if obj.category else ''

    def get_partner_profile_picture(self, obj):
        profile = getattr(obj.partner.user, 'customer_profile', None)
        if profile and profile.profile_picture:
            request = self.context.get('request')
            photo_url = profile.profile_picture.url
            if request:
                return request.build_absolute_uri(photo_url)
            from django.conf import settings
            domain = getattr(settings, 'BACKEND_URL', 'http://127.0.0.1:8000').rstrip('/')
            return f"{domain}{photo_url}"
        return None

    def get_partner_location(self, obj):
        loc = getattr(obj.partner.user, 'location', None)
        if loc and loc.latitude and loc.longitude:
            return {
                'latitude': str(loc.latitude),
                'longitude': str(loc.longitude),
                'address': loc.address or '',
            }
        return None


class ServiceDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a single service.
    """
    category = CategorySerializer(read_only=True)
    partner = PartnerProfileSerializer(read_only=True)
    images = ServiceImageSerializer(many=True, read_only=True)
    partner_location = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'description', 'price', 'price_unit', 'min_order_qty',
            'category', 'partner', 'status', 'is_available',
            'partner_location', 'service_radius_km',
            'specifications', 'images', 'created_at', 'updated_at'
        ]

    def get_partner_location(self, obj):
        loc = getattr(obj.partner.user, 'location', None)
        if loc and loc.latitude and loc.longitude:
            return {
                'latitude': str(loc.latitude),
                'longitude': str(loc.longitude),
                'address': loc.address or '',
            }
        return None


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
            'service_radius_km', 'specifications', 'images'
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
            'is_available', 'service_radius_km', 'specifications'
        ]
