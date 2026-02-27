from rest_framework import serializers
from .models import State, District, Tahsil, Village


class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ['id', 'name', 'code']


class DistrictSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source='state.name', read_only=True, default=None)

    class Meta:
        model = District
        fields = ['id', 'name', 'state', 'state_name']


class TahsilSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(source='district.name', read_only=True, default=None)

    class Meta:
        model = Tahsil
        fields = ['id', 'name', 'district', 'district_name']

class VillageSerializer(serializers.ModelSerializer):
    tahsil_name = serializers.CharField(source='tahasil.name', read_only=True, default=None)

    class Meta:
        model = Village
        fields = ['id', 'name', 'tahasil', 'tahsil_name']

class LocationUpdateSerializer(serializers.Serializer):
    """
    Dedicated serializer for updating user location (lat/lng/address).
    Used by the UserLocationView endpoint.
    """
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
