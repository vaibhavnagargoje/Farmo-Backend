# apps/services/serializers.py
from rest_framework import serializers
from .models import Category, Service, ServiceImage, ServicePriceUnit
from partners.serializers import PartnerProfileSerializer


def get_request_param(request, key, default=None):
    if not request:
        return default
    params = getattr(request, 'query_params', getattr(request, 'GET', {}))
    return params.get(key, default)


def get_request_lang(request, default='en'):
    """
    Extract user language preference from query param, Accept-Language header,
    or user profile.
    """
    if not request:
        return default
    # 1. Query parameter ?lang=
    params = getattr(request, 'query_params', getattr(request, 'GET', {}))
    lang = params.get('lang')
    if lang:
        return str(lang).strip().lower()
    # 2. Header Accept-Language
    headers = getattr(request, 'headers', {})
    accept_lang = headers.get('Accept-Language') or getattr(request, 'META', {}).get('HTTP_ACCEPT_LANGUAGE')
    if accept_lang:
        lang_code = accept_lang.split(',')[0].split('-')[0].strip().lower()
        if lang_code in ['mr', 'hi', 'en']:
            return lang_code
    # 3. Authenticated user's preferred_language
    user = getattr(request, 'user', None)
    if user and user.is_authenticated and getattr(user, 'preferred_language', None):
        return user.preferred_language
    return default


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for Service Categories.
    Supports: ?lang=mr for translated names, ?lat=&lng= for zone pricing.
    """
    name = serializers.SerializerMethodField()
    instant_price = serializers.SerializerMethodField()
    instant_price_unit = serializers.SerializerMethodField()
    instant_price_unit_display = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'name_translations', 'slug', 'icon', 'is_active', 'instant_price', 'instant_price_unit', 'instant_price_unit_display', 'instant_enabled']
        read_only_fields = ['id', 'slug']

    def _get_lang(self):
        return get_request_lang(self.context.get('request'))

    def get_name(self, obj):
        """Return translated name using Category.get_name(lang)."""
        lang = self._get_lang()
        return obj.get_name(lang)

    def _resolve_zone_price(self, obj):
        """Resolve zone price once and cache on the serializer instance."""
        cache_key = f'_zone_cache_{obj.pk}'
        if not hasattr(self, cache_key):
            request = self.context.get('request')
            result = None
            if request:
                lat = get_request_param(request, 'lat')
                lng = get_request_param(request, 'lng')
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
        return obj.instant_price_unit.key if obj.instant_price_unit else 'HOUR'

    def get_instant_price_unit_display(self, obj):
        resolved = self._resolve_zone_price(obj)
        unit = obj.instant_price_unit
        if unit:
            return unit.get_name(self._get_lang())
        return 'Hour'


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
    category = CategorySerializer(read_only=True)
    category_name = serializers.SerializerMethodField()
    category_name_translations = serializers.JSONField(source='category.name_translations', read_only=True, default=dict)
    partner_name = serializers.CharField(source='partner.user.customer_profile.full_name', read_only=True, default='')
    partner_id = serializers.IntegerField(source='partner.id', read_only=True)
    partner_rating = serializers.DecimalField(source='partner.rating', max_digits=3, decimal_places=2, read_only=True)
    partner_profile_picture = serializers.SerializerMethodField()
    thumbnail = serializers.SerializerMethodField()
    partner_location = serializers.SerializerMethodField()
    images = ServiceImageSerializer(many=True, read_only=True)
    # Distance in km from user's location — populated by Haversine annotation in ServiceListView
    distance_km = serializers.SerializerMethodField()
    price_unit = serializers.SerializerMethodField()
    price_unit_id = serializers.IntegerField(source='price_unit.id', read_only=True)
    price_unit_display = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'description', 'price', 'price_unit', 'price_unit_id', 'price_unit_display', 'category', 'category_name', 'category_name_translations',
            'partner_name', 'partner_id', 'partner_rating', 'partner_profile_picture', 'status', 'is_available', 'thumbnail',
            'partner_location', 'service_radius_km', 'images', 'distance_km'
        ]

    def get_thumbnail(self, obj):
        thumbnail = obj.images.filter(is_thumbnail=True).first()
        if thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(thumbnail.image.url)
        return None

    def get_category_name(self, obj):
        lang = get_request_lang(self.context.get('request'))
        if obj.category:
            return obj.category.get_name(lang)
        return ''

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

    def get_price_unit(self, obj):
        """Return price unit key string for backward compatibility."""
        return obj.price_unit.key if obj.price_unit else 'HOUR'

    def get_price_unit_display(self, obj):
        if not obj.price_unit:
            return 'Hour'
        lang = get_request_lang(self.context.get('request'))
        return obj.price_unit.get_name(lang)

    def get_distance_km(self, obj):
        """Return distance annotated by ServiceListView's Haversine query, rounded to 1 decimal."""
        dist = getattr(obj, 'distance', None)
        if dist is not None:
            return round(float(dist), 1)
        return None


class ServiceDetailSerializer(serializers.ModelSerializer):
    """
    Full detail serializer for viewing a single service.
    """
    category = CategorySerializer(read_only=True)
    category_name = serializers.SerializerMethodField()
    partner = PartnerProfileSerializer(read_only=True)
    images = ServiceImageSerializer(many=True, read_only=True)
    partner_location = serializers.SerializerMethodField()
    price_unit = serializers.SerializerMethodField()
    price_unit_id = serializers.IntegerField(source='price_unit.id', read_only=True)
    price_unit_display = serializers.SerializerMethodField()

    class Meta:
        model = Service
        fields = [
            'id', 'title', 'description', 'price', 'price_unit', 'price_unit_id', 'price_unit_display', 'min_order_qty',
            'category', 'category_name', 'partner', 'status', 'is_available',
            'partner_location', 'service_radius_km',
            'specifications', 'images', 'created_at', 'updated_at'
        ]

    def get_category_name(self, obj):
        lang = get_request_lang(self.context.get('request'))
        if obj.category:
            return obj.category.get_name(lang)
        return ''

    def get_price_unit(self, obj):
        """Return price unit key string for backward compatibility."""
        return obj.price_unit.key if obj.price_unit else 'HOUR'

    def get_price_unit_display(self, obj):
        if not obj.price_unit:
            return 'Hour'
        lang = get_request_lang(self.context.get('request'))
        return obj.price_unit.get_name(lang)

    def get_partner_location(self, obj):
        loc = getattr(obj.partner.user, 'location', None)
        if loc and loc.latitude and loc.longitude:
            return {
                'latitude': str(loc.latitude),
                'longitude': str(loc.longitude),
                'address': loc.address or '',
            }
        return None


class ServicePriceUnitSerializer(serializers.ModelSerializer):
    """
    Serializer for the ServicePriceUnit endpoint.
    Returns id, key, value, label, and translations for each unit.
    """
    label = serializers.SerializerMethodField()
    label_translations = serializers.DictField(source='name_translations')
    value = serializers.CharField(source='key', read_only=True)

    class Meta:
        model = ServicePriceUnit
        fields = ['id', 'key', 'value', 'label', 'label_translations']

    def get_label(self, obj):
        lang = get_request_lang(self.context.get('request'))
        return obj.get_name(lang)


class PriceUnitRelatedField(serializers.Field):
    """
    Accepts either an integer ID (FK pk) or a string key ('HOUR', 'ACRE')
    on writes, and returns the key string on representation.
    """
    def to_internal_value(self, data):
        if not data:
            raise serializers.ValidationError("Price unit is required.")
        if isinstance(data, ServicePriceUnit):
            return data
        # Try integer ID
        try:
            unit_id = int(data)
            unit = ServicePriceUnit.objects.filter(id=unit_id, is_active=True).first()
            if unit:
                return unit
        except (ValueError, TypeError):
            pass
        # Try key string
        if isinstance(data, str):
            unit = ServicePriceUnit.objects.filter(key=data.strip().upper(), is_active=True).first()
            if unit:
                return unit
        raise serializers.ValidationError(f"Invalid price unit '{data}'.")

    def to_representation(self, value):
        if isinstance(value, ServicePriceUnit):
            return value.key
        return str(value)


class ServiceCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for Partners to create a new Service.
    """
    price_unit = PriceUnitRelatedField()
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
    price_unit = PriceUnitRelatedField(required=False)

    class Meta:
        model = Service
        fields = [
            'title', 'description', 'price', 'price_unit', 'min_order_qty',
            'is_available', 'service_radius_km', 'specifications'
        ]
