# apps/availability/serializers.py
from rest_framework import serializers
from .models import BusyDay


class BusyDaySerializer(serializers.ModelSerializer):
    """Serializer for individual BusyDay records."""

    class Meta:
        model = BusyDay
        fields = [
            'id', 'date', 'entity_type', 'service',
            'marked_by', 'reason', 'created_at',
        ]
        read_only_fields = ['id', 'marked_by', 'created_at']


class CalendarMonthSerializer(serializers.Serializer):
    """
    Returns a list of busy dates for a given month.
    Optimized for calendar UI — just a flat list of date strings.
    """
    busy_dates = serializers.ListField(child=serializers.DateField())
    month = serializers.IntegerField()
    year = serializers.IntegerField()


class ToggleBusyDaySerializer(serializers.Serializer):
    """
    Used by workers (app) and agents (admin) to mark/unmark a date as busy.
    POST with a date → if BusyDay exists, delete it (mark free). If not, create it (mark busy).
    """
    date = serializers.DateField()
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    # For machinery: optionally specify which service/machine
    service_id = serializers.IntegerField(required=False, allow_null=True)
