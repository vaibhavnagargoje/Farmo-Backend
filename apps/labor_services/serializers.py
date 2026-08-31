from rest_framework import serializers
from .models import LaborCategory, LaborServiceType, LaborServiceOffering, LaborPriceUnit


class LaborServiceTypeSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = LaborServiceType
        fields = ['id', 'name', 'display_name', 'slug', 'icon', 'cover_image', 'default_price_unit']

    def get_display_name(self, obj):
        request = self.context.get('request')
        lang = request.query_params.get('lang', 'en') if request else 'en'
        if lang != 'en' and obj.name_translations:
            translated = obj.name_translations.get(lang)
            if translated:
                return translated
        return obj.name


class LaborServiceOfferingSerializer(serializers.ModelSerializer):
    """
    Read/write serializer for per-skill pricing entries.
    On read: returns nested service_type info + pricing.
    On write: accepts service_type_id + pricing fields.
    """
    service_type = LaborServiceTypeSerializer(read_only=True)
    service_type_id = serializers.IntegerField(write_only=True)
    price_unit_display = serializers.SerializerMethodField()

    class Meta:
        model = LaborServiceOffering
        fields = [
            'id', 'service_type', 'service_type_id',
            'price', 'price_unit', 'price_unit_display', 'note',
        ]

    def get_price_unit_display(self, obj):
        """Return translated price unit label from the LaborPriceUnit model."""
        request = self.context.get('request')
        lang = request.query_params.get('lang', 'en') if request else 'en'
        return obj.price_unit.get_name(lang)


class LaborCategorySerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    service_types = LaborServiceTypeSerializer(many=True, read_only=True)
    worker_count = serializers.SerializerMethodField()

    class Meta:
        model = LaborCategory
        fields = ['id', 'name', 'display_name', 'slug', 'icon', 'cover_image', 'service_types', 'worker_count']

    def get_display_name(self, obj):
        request = self.context.get('request')
        lang = request.query_params.get('lang', 'en') if request else 'en'
        if lang != 'en' and obj.name_translations:
            translated = obj.name_translations.get(lang)
            if translated:
                return translated
        return obj.name

    def get_worker_count(self, obj):
        # We can implement an annotation or a basic count here.
        # For now, we will return 0 or calculate it.
        # A more optimal way is to annotate the queryset in the view.
        return getattr(obj, 'worker_count_annotated', 0)


class PriceUnitSerializer(serializers.ModelSerializer):
    """
    Serializer for the LaborPriceUnit endpoint.
    Returns id, label, and translations for each unit.
    """
    label = serializers.CharField(source='name')
    label_translations = serializers.DictField(source='name_translations')

    class Meta:
        model = LaborPriceUnit
        fields = ['id', 'label', 'label_translations']
