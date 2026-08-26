from rest_framework import serializers
from .models import LaborCategory, LaborServiceType

class LaborServiceTypeSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = LaborServiceType
        fields = ['id', 'name', 'display_name', 'slug', 'icon', 'cover_image']

    def get_display_name(self, obj):
        request = self.context.get('request')
        lang = request.query_params.get('lang', 'en') if request else 'en'
        if lang != 'en' and obj.name_translations:
            translated = obj.name_translations.get(lang)
            if translated:
                return translated
        return obj.name

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
