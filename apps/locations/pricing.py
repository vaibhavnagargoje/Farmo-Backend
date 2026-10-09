"""
Compatibility import path for the location-aware price resolver.

The implementation lives in ``locations.views.pricing``. Other apps import
``locations.pricing``, so this module re-exports it to keep them working.
"""

from .views.pricing import _haversine_km, resolve_instant_price, resolve_instant_price_detail

__all__ = ['_haversine_km', 'resolve_instant_price', 'resolve_instant_price_detail']
