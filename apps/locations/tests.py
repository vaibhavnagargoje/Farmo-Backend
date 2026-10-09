from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from bookings.models import Booking
from locations.models import PricingZone, UserLocation
from locations.pricing import resolve_instant_price, resolve_instant_price_detail
from partners.models import PartnerProfile
from services.models import Category, Service, ServicePriceUnit
from users.models import CustomerProfile, User

PUNE = (Decimal("18.524609"), Decimal("73.878624"))
MUMBAI = (19.0760, 72.8777)


def make_units():
    hour, _ = ServicePriceUnit.objects.update_or_create(
        key="HOUR", defaults={"name": "Per Hour", "name_translations": {"mr": "प्रति तास"}},
    )
    acre, _ = ServicePriceUnit.objects.update_or_create(
        key="ACRE", defaults={"name": "Per Acre", "name_translations": {"mr": "प्रति एकर"}},
    )
    return hour, acre


class ResolveInstantPriceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hour, cls.acre = make_units()
        cls.category = Category.objects.create(
            name="Rotavator", slug="zone-rotavator", instant_price=Decimal("500.00"),
            instant_price_unit=cls.hour,
        )

    def make_zone(self, name, center=None, radius=25, price="1000", unit=None, **kwargs):
        lat, lng = center if center else (None, None)
        return PricingZone.objects.create(
            category=self.category, name=name, center_lat=lat, center_lng=lng,
            radius_km=radius, price=Decimal(price), price_unit=unit or self.acre, **kwargs,
        )

    def test_no_zones_uses_category_price(self):
        self.assertEqual(resolve_instant_price(self.category, *PUNE), (500.0, "HOUR", None))

    def test_customer_inside_zone_gets_zone_price_and_unit(self):
        self.make_zone("Pune", PUNE, radius=25, price="3000")
        self.assertEqual(resolve_instant_price(self.category, 18.55, 73.90), (3000.0, "ACRE", "Pune"))

    def test_closest_zone_wins_when_zones_overlap(self):
        self.make_zone("Far", PUNE, radius=100, price="1000")
        self.make_zone("Near", (Decimal("18.600000"), Decimal("73.900000")), radius=100, price="2000")
        self.assertEqual(resolve_instant_price(self.category, 18.60, 73.90)[2], "Near")

    def test_outside_every_zone_uses_default_zone(self):
        self.make_zone("Pune", PUNE, radius=25, price="3000")
        self.make_zone("Fallback", price="1500", unit=self.hour, is_default=True)
        self.assertEqual(resolve_instant_price(self.category, *MUMBAI), (1500.0, "HOUR", "Fallback"))

    def test_outside_every_zone_without_default_uses_category_price(self):
        self.make_zone("Pune", PUNE, radius=25, price="3000")
        self.assertEqual(resolve_instant_price(self.category, *MUMBAI), (500.0, "HOUR", None))

    def test_inactive_zone_is_ignored(self):
        self.make_zone("Pune", PUNE, radius=25, price="3000", is_active=False)
        self.assertEqual(resolve_instant_price(self.category, *PUNE), (500.0, "HOUR", None))

    def test_detail_returns_unit_object(self):
        self.make_zone("Pune", PUNE, radius=25, price="3000")
        price, unit, zone_name = resolve_instant_price_detail(self.category, *PUNE)
        self.assertEqual((price, unit, zone_name), (3000.0, self.acre, "Pune"))


class PricingZoneCleanTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hour, cls.acre = make_units()
        cls.category = Category.objects.create(name="Rotavator", slug="clean-rotavator", instant_price_unit=cls.hour)

    def zone(self, **kwargs):
        values = {"category": self.category, "name": "Z", "price": Decimal("100"), "price_unit": self.acre}
        values.update(kwargs)
        return PricingZone(**values)

    def test_default_zone_with_coordinates_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.zone(is_default=True, center_lat=PUNE[0], center_lng=PUNE[1]).clean()

    def test_default_zone_without_coordinates_is_valid(self):
        self.zone(is_default=True).clean()

    def test_geographic_zone_requires_both_coordinates(self):
        with self.assertRaises(ValidationError):
            self.zone().clean()
        with self.assertRaises(ValidationError):
            self.zone(center_lat=PUNE[0]).clean()
        self.zone(center_lat=PUNE[0], center_lng=PUNE[1]).clean()

    def test_only_one_active_default_per_category(self):
        PricingZone.objects.create(
            category=self.category, name="Default A", price=Decimal("100"), price_unit=self.acre, is_default=True,
        )
        with self.assertRaises(ValidationError):
            self.zone(name="Default B", is_default=True).clean()
        self.zone(name="Default B", is_default=True, is_active=False).clean()


class ZonePricingApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hour, cls.acre = make_units()
        cls.category = Category.objects.create(
            name="Rotavator", slug="api-rotavator", instant_price=Decimal("500.00"),
            instant_price_unit=cls.hour,
        )
        PricingZone.objects.create(
            category=cls.category, name="Pune", center_lat=PUNE[0], center_lng=PUNE[1],
            radius_km=25, price=Decimal("3000"), price_unit=cls.acre,
        )
        cls.customer = User.objects.create(phone_number="9876543210")

    def category_payload(self, query=""):
        response = self.client.get(reverse("services:category-list") + query)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        data = data.get("results", data) if isinstance(data, dict) else data
        return next(c for c in data if c["slug"] == self.category.slug)

    def test_categories_without_location_return_global_price(self):
        payload = self.category_payload()
        self.assertEqual((payload["instant_price"], payload["instant_price_unit"]), ("500.00", "HOUR"))
        self.assertEqual(payload["instant_price_unit_display"], "Per Hour")

    def test_categories_inside_zone_return_zone_price_unit_and_display(self):
        payload = self.category_payload("?lat=18.55&lng=73.90")
        self.assertEqual((payload["instant_price"], payload["instant_price_unit"]), ("3000.00", "ACRE"))
        self.assertEqual(payload["instant_price_unit_display"], "Per Acre")

    def test_categories_display_unit_is_translated(self):
        payload = self.category_payload("?lat=18.55&lng=73.90&lang=mr")
        self.assertEqual(payload["instant_price_unit_display"], "प्रति एकर")

    def test_categories_outside_zone_return_global_price(self):
        payload = self.category_payload("?lat=19.0760&lng=72.8777")
        self.assertEqual((payload["instant_price"], payload["instant_price_unit"]), ("500.00", "HOUR"))

    @patch("notifications.signals.send_push_notification")
    def test_instant_booking_uses_zone_price_and_ignores_client_unit(self, _push):
        client = APIClient()
        client.force_authenticate(self.customer)
        response = client.post(reverse("bookings:instant-booking-create"), {
            "category_id": self.category.id,
            "quantity": 2,
            "price_unit": "HOUR",  # what an older app build sends (the global category unit)
            "address": "Pune farm",
            "lat": 18.55,
            "lng": 73.90,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)

        booking = Booking.objects.get(customer=self.customer)
        self.assertEqual(booking.unit_price, Decimal("3000.00"))
        self.assertEqual(booking.price_unit, "ACRE")
        self.assertEqual(booking.total_amount, Decimal("6000.00"))


class QuickBookProvidersApiTests(TestCase):
    """The quick-book screen lists providers with ?lat=&lng= (nearest first)."""

    @classmethod
    def setUpTestData(cls):
        cls.hour, _ = make_units()
        cls.category = Category.objects.create(name="Rotavator", slug="qb-rotavator", instant_price_unit=cls.hour)
        cls.near = cls.make_service("9001000001", "Near Tractor", "18.530000", "73.880000")
        cls.far = cls.make_service("9001000002", "Far Tractor", "18.700000", "74.000000")
        cls.no_location = cls.make_service("9001000003", "No Location Tractor")

    @classmethod
    def make_service(cls, phone, title, lat=None, lng=None):
        user = User.objects.create(phone_number=phone, role=User.Role.PARTNER)
        CustomerProfile.objects.create(user=user, full_name=title)
        if lat:
            UserLocation.objects.create(user=user, latitude=Decimal(lat), longitude=Decimal(lng))
        partner = PartnerProfile.objects.create(
            user=user, business_name=title, partner_type=PartnerProfile.PartnerType.MACHINERY_OWNER,
            is_verified=True,
        )
        return Service.objects.create(
            partner=partner, title=title, category=cls.category, price=Decimal("800.00"),
            price_unit=cls.hour, status=Service.Status.ACTIVE, service_radius_km=12,
        )

    def titles(self, query):
        response = self.client.get(reverse("services:service-list") + query)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        return [s["title"] for s in data.get("results", data)]

    def test_lat_lng_sorts_nearest_first_and_skips_providers_without_location(self):
        self.assertEqual(
            self.titles(f"?category={self.category.slug}&lat=18.524609&lng=73.878624"),
            ["Near Tractor", "Far Tractor"],
        )

    def test_legacy_latitude_longitude_params_are_ignored(self):
        self.assertEqual(
            set(self.titles(f"?category={self.category.slug}&latitude=18.524609&longitude=73.878624")),
            {"Near Tractor", "Far Tractor", "No Location Tractor"},
        )
