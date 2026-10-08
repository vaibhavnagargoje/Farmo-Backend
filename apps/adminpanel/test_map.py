"""Dispatch regression tests; fixtures never create real booking notifications."""

import json
from datetime import time, timedelta
from decimal import Decimal
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from availability.models import BusyDay
from bookings.models import Booking, InstantBookingRequest
from locations.models import UserLocation
from partners.models import PartnerProfile
from services.models import Category, Service, ServicePriceUnit
from users.models import CustomerProfile, User


class MapDispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create(phone_number="9001000000", is_staff=True)
        cls.customer = User.objects.create(phone_number="9876543210")
        CustomerProfile.objects.update_or_create(user=cls.customer, defaults={"full_name": "Private Farmer Name"})
        cls.unit, _ = ServicePriceUnit.objects.update_or_create(
            key="ACRE", defaults={"name": "Per Acre", "name_translations": {"mr": "प्रति एकर"}},
        )
        cls.category = Category.objects.create(
            name="Ploughing", slug="map-ploughing", name_translations={"mr": "नांगरणी"},
        )
        cls.other_category = Category.objects.create(name="Harvesting", slug="map-harvesting")
        cls.partner = cls.make_partner("9001000001", "Primary Machinery")
        cls.alternative = cls.make_partner("9001000002", "Alternative Machinery")
        cls.service = cls.make_service(cls.partner, "Primary Tractor")
        cls.alternative_service = cls.make_service(cls.alternative, "Alternative Tractor")
        cls.work_date = timezone.localdate() + timedelta(days=2)
        cls.booking = Booking.objects.bulk_create([
            Booking(
                customer=cls.customer, provider=cls.partner, service=cls.service,
                category=cls.category, booking_id="BK-MAP-PRIVATE",
                status=Booking.Status.PENDING, booking_type=Booking.BookingType.SCHEDULED,
                scheduled_date=cls.work_date, scheduled_time=time(9, 30),
                address="Private Farm Gate 17, Exact Road, Private Village",
                lat=Decimal("18.123456"), lng=Decimal("73.654321"),
                quantity=3, price_unit="ACRE", unit_price=Decimal("750.00"),
                total_amount=Decimal("2250.00"), note="PRIVATE WORK INSTRUCTIONS",
                job_otp="938217", start_job_otp="873912", end_job_otp="719283",
            ),
        ])[0]

    @classmethod
    def make_partner(cls, phone, name, **kwargs):
        user = User.objects.create(phone_number=phone, role=User.Role.PARTNER)
        CustomerProfile.objects.create(user=user, full_name=name)
        UserLocation.objects.create(user=user, latitude=Decimal("18.130000"), longitude=Decimal("73.660000"))
        return PartnerProfile.objects.create(
            user=user, business_name=name, partner_type=PartnerProfile.PartnerType.MACHINERY_OWNER,
            is_verified=True, **kwargs,
        )

    @classmethod
    def make_service(cls, partner, title, **kwargs):
        values = {
            "partner": partner, "title": title, "category": cls.category,
            "price": Decimal("800.00"), "price_unit": cls.unit,
            "status": Service.Status.ACTIVE, "service_radius_km": 12,
        }
        values.update(kwargs)
        return Service.objects.create(**values)

    def setUp(self):
        self.client.force_login(self.agent)
        self.push_patch = patch("notifications.signals.send_push_notification")
        self.push_patch.start()
        self.addCleanup(self.push_patch.stop)
        self.area_patch = patch("adminpanel.map_messages.coarse_area_label", return_value="बारामती, पुणे")
        self.area_lookup = self.area_patch.start()
        self.addCleanup(self.area_patch.stop)

    def draft(self, partner=None, **extra):
        return self.client.post(reverse("adminpanel:map-message-draft"), {
            "booking_id": self.booking.booking_id,
            "partner_id": (partner or self.partner).pk,
            **extra,
        })

    def assign(self, partner=None, **extra):
        return self.client.post(reverse("adminpanel:map-assign-partner"), {
            "booking_id": self.booking.booking_id,
            "partner_id": (partner or self.partner).pk,
            **extra,
        })

    def map_payload(self, **filters):
        response = self.client.get(reverse("adminpanel:map-data"), filters)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["success"])
        return response.json()

    def candidate(self, payload, partner=None):
        booking = next(item for item in payload["bookings"] if item["id"] == self.booking.pk)
        return next(item for item in booking["candidates"]
                    if item["provider_id"] == (partner or self.partner).pk)

    def assert_limited(self, response):
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["detail_level"], "limited")
        serialized = str(payload)
        for private in [
            "Private Farmer Name", self.customer.phone_number, self.booking.address,
            "18.123456", "73.654321", self.booking.note,
            self.booking.job_otp, self.booking.start_job_otp, self.booking.end_job_otp,
            "maps.google", "google.com/maps",
        ]:
            self.assertNotIn(private, serialized)
        self.assertIn("बारामती", payload["text"])
        self.assertIn(self.booking.booking_id, payload["text"])
        return payload

    def test_pending_scheduled_provider_is_not_authorized_for_customer_details(self):
        for status in [Booking.Status.PENDING, Booking.Status.SEARCHING]:
            with self.subTest(status=status):
                Booking.objects.filter(pk=self.booking.pk).update(status=status)
                payload = self.assert_limited(self.draft())
                self.assertEqual(payload["booking_status"], status)
                self.assertIsNotNone(payload["distance_km"])

    def test_full_marathi_draft_only_for_current_confirmed_or_working_provider(self):
        for status in [Booking.Status.CONFIRMED, Booking.Status.IN_PROGRESS]:
            with self.subTest(status=status):
                Booking.objects.filter(pk=self.booking.pk).update(status=status)
                response = self.draft()
                self.assertEqual(response.status_code, 200, response.content)
                payload = response.json()
                self.assertEqual(payload["detail_level"], "full")
                self.assertRegex(payload["text"], r"[\u0900-\u097f]")
                for detail in ["Private Farmer Name", self.customer.phone_number, self.booking.address,
                               self.booking.note, "18.123456", "73.654321"]:
                    self.assertIn(detail, payload["text"])
                for otp in [self.booking.job_otp, self.booking.start_job_otp, self.booking.end_job_otp]:
                    self.assertNotIn(otp, payload["text"])

    def test_assignment_change_revokes_old_recipients_full_draft(self):
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.CONFIRMED)
        self.assertEqual(self.draft().json()["detail_level"], "full")
        Booking.objects.filter(pk=self.booking.pk).update(provider=self.alternative)
        payload = self.assert_limited(self.draft())
        self.assertEqual(payload["provider_id"], self.alternative.pk)
        self.assertNotIn("नवीन काम उपलब्ध", payload["text"])
        self.assertEqual(self.draft(self.alternative).json()["detail_level"], "full")

    def test_assignment_or_cancellation_during_area_lookup_is_rechecked(self):
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.CONFIRMED)

        def change_assignee(*args):
            Booking.objects.filter(pk=self.booking.pk).update(provider=self.alternative)
            return "बारामती, पुणे"

        self.area_lookup.side_effect = change_assignee
        self.assert_limited(self.draft())

        def cancel_booking(*args):
            Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.CANCELLED)
            return "बारामती, पुणे"

        self.area_lookup.side_effect = cancel_booking
        self.assertEqual(self.draft(self.alternative).status_code, 409)

    def test_terminal_booking_cannot_generate_a_stale_message(self):
        for status in [Booking.Status.CANCELLED, Booking.Status.REJECTED,
                       Booking.Status.EXPIRED, Booking.Status.COMPLETED]:
            with self.subTest(status=status):
                Booking.objects.filter(pk=self.booking.pk).update(status=status)
                response = self.draft()
                self.assertEqual(response.status_code, 409, response.content)
                self.assertNotIn("text", response.json())
        self.area_lookup.assert_not_called()

    def test_no_coarse_area_never_falls_back_to_full_address(self):
        self.area_lookup.return_value = ""
        response = self.draft()
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertFalse(payload["area_available"])
        self.assertEqual(payload["area_label"], "")
        for private in [self.booking.address, "Private Farm Gate", "Private Village"]:
            self.assertNotIn(private, payload["text"])
        self.assertRegex(payload["text"], r"[\u0900-\u097f]")

    def test_marathi_message_is_correctly_encoded_for_whatsapp_and_sms(self):
        payload = self.draft().json()
        whatsapp = urlsplit(payload["whatsapp_url"])
        sms = urlsplit(payload["sms_url"])
        self.assertEqual(whatsapp.netloc, "wa.me")
        self.assertEqual(whatsapp.path.strip("/"), "919001000001")
        self.assertEqual(parse_qs(whatsapp.query)["text"], [payload["text"]])
        self.assertEqual(sms.scheme, "sms")
        self.assertEqual(parse_qs(sms.query)["body"], [payload["text"]])

    def test_map_endpoints_require_admin_access_and_drafts_require_post(self):
        self.assertEqual(self.client.get(reverse("adminpanel:map-message-draft")).status_code, 405)
        for user in [None, self.customer]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            for name, status in [("map-view", 302), ("map-data", 403)]:
                with self.subTest(user=user, endpoint=name):
                    self.assertEqual(self.client.get(reverse("adminpanel:" + name)).status_code, status)
            self.assertEqual(self.draft().status_code, 403)
            self.assertEqual(self.assign().status_code, 403)
        self.area_lookup.assert_not_called()

    def test_map_page_renders_message_dialog_and_endpoints(self):
        self.client.force_login(self.agent)
        response = self.client.get(reverse("adminpanel:map-view"))
        self.assertEqual(response.status_code, 200)
        for marker in ("messageDraftDialog", "messageDraftBody", "messageDraftActions", "mapNotice", "mapRefreshBtn",
                       reverse("adminpanel:map-data"), reverse("adminpanel:map-message-draft"), reverse("adminpanel:map-assign-partner")):
            self.assertContains(response, marker)

    def test_assignment_preserves_scheduled_service_owner_and_rejects_second_winner(self):
        rejected = self.assign(self.alternative, service_id=self.alternative_service.pk)
        self.assertEqual(rejected.status_code, 400, rejected.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)
        self.assertEqual(self.booking.service_id, self.service.pk)
        accepted = self.assign()
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CONFIRMED)
        self.assertEqual(self.booking.provider_id, self.partner.pk)
        self.assertEqual(self.booking.accepted_by_agent, self.agent)
        self.assertEqual(self.booking.service_id, self.service.pk)
        self.assertEqual(self.booking.unit_price, Decimal("750.00"))
        self.assertEqual(self.booking.total_amount, Decimal("2250.00"))
        second = self.assign(self.alternative)
        self.assertEqual(second.status_code, 409, second.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.provider_id, self.partner.pk)

    def test_assignment_rechecks_live_availability(self):
        self.client.get(reverse("adminpanel:map-data"))
        BusyDay.objects.create(partner=self.partner, service=self.service,
                               entity_type=BusyDay.EntityType.SERVICE, date=self.work_date,
                               marked_by=BusyDay.MarkedBy.SELF)
        response = self.assign()
        self.assertEqual(response.status_code, 400, response.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.PENDING)

    def test_instant_assignment_selects_matching_service_and_expires_competing_pings(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            provider=None, service=None, booking_type=Booking.BookingType.INSTANT,
            status=Booking.Status.SEARCHING, expires_at=timezone.now() + timedelta(minutes=10),
        )
        InstantBookingRequest.objects.bulk_create([
            InstantBookingRequest(booking=self.booking, provider=partner)
            for partner in [self.partner, self.alternative]
        ])
        response = self.assign()
        self.assertEqual(response.status_code, 200, response.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.service_id, self.service.pk)
        self.assertEqual(self.booking.provider_id, self.partner.pk)
        self.assertEqual(self.booking.unit_price, Decimal("750.00"))
        self.assertEqual(self.booking.total_amount, Decimal("2250.00"))
        self.assertFalse(self.booking.instant_requests.filter(status=InstantBookingRequest.RequestStatus.PENDING).exists())

    def test_expired_search_is_not_assignable(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            booking_type=Booking.BookingType.INSTANT, status=Booking.Status.SEARCHING,
            provider=None, service=None, expires_at=timezone.now() - timedelta(seconds=1),
        )
        response = self.assign()
        self.assertEqual(response.status_code, 409, response.content)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.provider_id, None)

    def test_refresh_exposes_service_prices_profile_links_and_no_otps(self):
        payload = self.map_payload()
        provider = next(item for item in payload["partners"] if item["id"] == self.partner.pk)
        service = next(item for item in provider["service_details"] if item["id"] == self.service.pk)
        self.assertEqual(service["category_id"], self.category.pk)
        self.assertEqual(service["price"], 800)
        self.assertEqual(service["price_unit"], "ACRE")
        self.assertEqual(service["price_unit_label"], "Per Acre")
        self.assertEqual(service["radius_km"], 12)
        self.assertEqual(service["min_order_qty"], 1)
        self.assertEqual(provider["profile_url"], reverse("adminpanel:user-detail", kwargs={"user_id": self.partner.user_id}))
        order = next(item for item in payload["bookings"] if item["id"] == self.booking.pk)
        self.assertEqual(order["customer_profile_url"], reverse("adminpanel:user-detail", kwargs={"user_id": self.customer.pk}))
        self.assertIsNone(order["accepted_provider_id"])
        self.assertTrue(self.candidate(payload)["is_eligible"])
        for otp in [self.booking.job_otp, self.booking.start_job_otp, self.booking.end_job_otp]:
            self.assertNotIn(otp, str(payload))
        self.assertTrue(payload["updated_at"])
        self.assertEqual(payload["stats"]["pending_bookings_count"], 1)
        self.area_lookup.assert_not_called()

    def test_machine_busy_does_not_mark_the_entire_owner_busy(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            booking_type=Booking.BookingType.INSTANT, service=None, provider=None,
        )
        spare = self.make_service(self.partner, "Spare Tractor")
        BusyDay.objects.create(partner=self.partner, service=self.service,
                               entity_type=BusyDay.EntityType.SERVICE, date=self.work_date,
                               marked_by=BusyDay.MarkedBy.SELF)
        payload = self.map_payload()
        provider = next(item for item in payload["partners"] if item["id"] == self.partner.pk)
        self.assertNotIn(self.work_date.isoformat(), provider["busy_dates"])
        machines = {item["id"]: item for item in provider["service_details"]}
        self.assertIn(self.work_date.isoformat(), machines[self.service.pk]["busy_dates"])
        self.assertEqual(machines[spare.pk]["busy_dates"], [])
        self.assertTrue(self.candidate(payload)["is_eligible"])
        self.assertEqual(self.candidate(payload)["service_id"], spare.pk)
        BusyDay.objects.create(partner=self.partner, date=self.work_date, marked_by=BusyDay.MarkedBy.SELF)
        unavailable = self.candidate(self.map_payload())
        self.assertFalse(unavailable["is_eligible"])
        self.assertIn("Partner busy on requested date", unavailable["reasons"])

    def test_matching_uses_requested_day_and_each_matching_service_radius(self):
        Booking.objects.filter(pk=self.booking.pk).update(
            booking_type=Booking.BookingType.INSTANT, service=None, provider=None,
        )
        self.make_service(self.partner, "Unrelated far-reaching machine", category=self.other_category, service_radius_km=100)
        UserLocation.objects.filter(user=self.partner.user).update(latitude=Decimal("18.500000"))
        outside = self.candidate(self.map_payload())
        self.assertFalse(outside["is_eligible"])
        self.assertFalse(outside["in_coverage"])
        self.assertIn("Outside service radius", outside["reasons"])
        UserLocation.objects.filter(user=self.partner.user).update(latitude=Decimal("18.130000"))
        BusyDay.objects.create(partner=self.partner, date=timezone.localdate(), marked_by=BusyDay.MarkedBy.SELF)
        self.assertTrue(self.candidate(self.map_payload())["is_eligible"])
        BusyDay.objects.create(partner=self.partner, date=self.work_date, marked_by=BusyDay.MarkedBy.SELF)
        self.assertFalse(self.candidate(self.map_payload())["is_eligible"])

    def test_matching_validates_units_minimums_service_and_partner_availability(self):
        hour, _ = ServicePriceUnit.objects.get_or_create(key="HOUR", defaults={"name": "Per Hour"})
        for changes, reason in [
            ({"price_unit": hour}, "Pricing unit differs from order"),
            ({"min_order_qty": Decimal("5")}, "Quantity below service minimum"),
            ({"is_available": False}, "Service unavailable"),
        ]:
            with self.subTest(changes=changes):
                Service.objects.filter(pk=self.service.pk).update(**changes)
                candidate = self.candidate(self.map_payload())
                self.assertFalse(candidate["is_eligible"])
                self.assertIn(reason, candidate["reasons"])
                self.assertEqual(self.assign().status_code, 400)
                Service.objects.filter(pk=self.service.pk).update(price_unit=self.unit, min_order_qty=1, is_available=True)
        PartnerProfile.objects.filter(pk=self.partner.pk).update(is_available=False)
        self.assertFalse(self.candidate(self.map_payload())["is_eligible"])
        self.assertEqual(self.assign().status_code, 400)
        PartnerProfile.objects.filter(pk=self.partner.pk).update(is_available=True)
        User.objects.filter(pk=self.partner.user_id).update(is_active=False)
        self.assertFalse(self.candidate(self.map_payload())["is_eligible"])
        self.assertEqual(self.assign().status_code, 400)

    def test_zero_coordinates_are_real_locations_and_missing_assignee_is_still_described(self):
        Booking.objects.filter(pk=self.booking.pk).update(lat=0, lng=0)
        UserLocation.objects.filter(user=self.partner.user).update(latitude=0, longitude=Decimal("0.01"))
        payload = self.map_payload()
        candidate = self.candidate(payload)
        self.assertTrue(candidate["is_eligible"])
        self.assertAlmostEqual(candidate["distance_km"], 1.11, places=2)
        UserLocation.objects.filter(user=self.partner.user).delete()
        Booking.objects.filter(pk=self.booking.pk).update(status=Booking.Status.CONFIRMED)
        payload = self.map_payload()
        self.assertNotIn(self.partner.pk, [item["id"] for item in payload["partners"]])
        order = next(item for item in payload["bookings"] if item["id"] == self.booking.pk)
        self.assertEqual(order["assigned_provider"]["id"], self.partner.pk)
        self.assertEqual(order["assigned_provider"]["phone"], self.partner.user.phone_number)
        self.assertEqual(order["accepted_provider_id"], self.partner.pk)
        self.assertIsNone(order["assigned_provider"]["lat"])

    def test_refresh_status_and_category_filters_and_invalid_inputs(self):
        self.assertEqual(len(self.map_payload(category=self.category.pk)["bookings"]), 1)
        self.assertEqual(self.map_payload(category=self.other_category.pk)["bookings"], [])
        self.assertEqual(self.map_payload(status=Booking.Status.CONFIRMED)["bookings"], [])
        for filters in [{"category": "not-an-id"}, {"status": "invalid"}]:
            response = self.client.get(reverse("adminpanel:map-data"), filters)
            self.assertLess(response.status_code, 500)
        for data in [{}, {"booking_id": self.booking.booking_id},
                     {"booking_id": self.booking.booking_id, "partner_id": "not-an-id"}]:
            response = self.client.post(reverse("adminpanel:map-message-draft"), data)
            self.assertIn(response.status_code, [400, 404])


@override_settings(GOOGLE_GEOCODING_API_KEY="test-key", GOOGLE_MAPS_API_KEY="")
class CoarseAreaTests(SimpleTestCase):
    def test_geocoder_only_uses_town_and_district_components(self):
        from .map_messages import coarse_area_label

        data = {"status": "OK", "results": [{
            "formatted_address": "PRIVATE EXACT HOUSE AND FARM ADDRESS",
            "address_components": [
                {"long_name": "PRIVATE HOUSE", "types": ["premise"]},
                {"long_name": "PRIVATE STREET", "types": ["route"]},
                {"long_name": "PRIVATE SUBLOCALITY", "types": ["sublocality"]},
                {"long_name": "  बारामती  ", "types": ["locality", "political"]},
                {"long_name": "पुणे", "types": ["administrative_area_level_2", "political"]},
                {"long_name": "महाराष्ट्र", "types": ["administrative_area_level_1", "political"]},
            ],
        }]}
        with patch("adminpanel.map_messages.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = json.dumps(data).encode("utf-8")
            self.assertEqual(coarse_area_label(18, 73), "बारामती, पुणे")
            self.assertLessEqual(network.call_args.kwargs["timeout"], 3)
            self.assertIn("language=mr", network.call_args.args[0])

    def test_missing_components_bad_data_or_network_failure_never_use_formatted_address(self):
        from .map_messages import coarse_area_label

        for response in [
            {"status": "OK", "results": [{"formatted_address": "PRIVATE EXACT ADDRESS"}]},
            {"status": "ZERO_RESULTS", "results": []},
            {"status": "REQUEST_DENIED", "error_message": "private diagnostic"},
            {"status": "OK", "results": None},
        ]:
            with self.subTest(response=response), patch("adminpanel.map_messages.urlopen") as network:
                network.return_value.__enter__.return_value.read.return_value = json.dumps(response).encode("utf-8")
                self.assertEqual(coarse_area_label(18, 73), "")
        with patch("adminpanel.map_messages.urlopen", side_effect=URLError("Unavailable")):
            self.assertEqual(coarse_area_label(18, 73), "")
        with patch("adminpanel.map_messages.urlopen") as network:
            network.return_value.__enter__.return_value.read.return_value = b"not-json"
            self.assertEqual(coarse_area_label(18, 73), "")

    def test_no_key_or_missing_coordinates_avoids_external_lookup(self):
        from .map_messages import coarse_area_label

        with patch("adminpanel.map_messages.urlopen") as network:
            self.assertEqual(coarse_area_label(None, 73), "")
            with override_settings(GOOGLE_GEOCODING_API_KEY="", GOOGLE_MAPS_API_KEY=""):
                self.assertEqual(coarse_area_label(18, 73), "")
            network.assert_not_called()
