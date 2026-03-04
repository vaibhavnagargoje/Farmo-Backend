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

    def to_internal_value(self, data):
        """
        Round lat/lng to 6 decimal places before DRF's strict
        DecimalField validation so high-precision floats from
        Google Maps / GPS don't cause a 400.
        """
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        for field in ('latitude', 'longitude'):
            if field in data and data[field] is not None:
                try:
                    data[field] = str(round(float(data[field]), 6))
                except (ValueError, TypeError):
                    pass  # let DRF's normal validation handle bad input
        return super().to_internal_value(data)
