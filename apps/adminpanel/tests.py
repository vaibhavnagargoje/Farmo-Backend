from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from availability.models import BusyDay
from bookings.models import Booking
from labor_services.models import LaborCategory, LaborDetails, LaborPriceUnit, LaborServiceType
from locations.models import UserLocation
from partners.models import PartnerProfile
from services.models import Category, Service, ServicePriceUnit
from users.models import CustomerProfile, User


class AvailabilityWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.agent = User.objects.create(phone_number="9000000000", is_staff=True)
        UserLocation.objects.create(user=cls.agent, latitude=0, longitude=0)
        cls.today = timezone.localdate()
        cls.selected = date(cls.today.year + 1, 1, 15)
        cls.skill = LaborServiceType.objects.create(
            name="Sowing & planting", slug="sowing",
            category=LaborCategory.objects.create(name="Farm work", slug="farm"),
        )
        cls.category = Category.objects.create(name="Tractors", slug="tractors")
        cls.nearby = cls.make_partner("9000000001", "Asha & Co", gender="F", longitude="0.01")
        cls.distant = cls.make_partner("9000000002", "Bala", gender="M", longitude="1")
        cls.machine = cls.make_partner(
            "9000000003", "Chandra", partner_type=PartnerProfile.PartnerType.MACHINERY_OWNER,
        )
        cls.offline = cls.make_partner("9000000004", "Offline", is_available=False)
        labor_price_unit = LaborPriceUnit.objects.create(name="Per Day")
        for partner, wage in [(cls.nearby, 500), (cls.distant, 300)]:
            details = LaborDetails.objects.create(partner=partner, daily_wage_estimate=wage)
            details.service_types.add(cls.skill, through_defaults={"price": wage, "price_unit": labor_price_unit})
        cls.service = Service.objects.create(
            partner=cls.machine, category=cls.category, title="Tractor",
            price=100, status=Service.Status.ACTIVE,
            price_unit=ServicePriceUnit.objects.create(key="day", name="Per Day"),
        )
        BusyDay.objects.create(partner=cls.nearby, date=cls.selected, marked_by=BusyDay.MarkedBy.AGENT)
        # Duplicate partner-level rows and individual assets must not inflate totals.
        BusyDay.objects.create(partner=cls.nearby, date=cls.selected, marked_by=BusyDay.MarkedBy.SELF)
        BusyDay.objects.create(
            partner=cls.machine, service=cls.service, date=cls.selected,
            marked_by=BusyDay.MarkedBy.SELF, entity_type=BusyDay.EntityType.SERVICE,
        )
        BusyDay.objects.create(partner=cls.offline, date=cls.today, marked_by=BusyDay.MarkedBy.SELF)
        Booking.objects.bulk_create([
            Booking(customer=cls.agent, booking_id="BK-PENDING", status=Booking.Status.PENDING,
                    scheduled_date=cls.selected, address="Farm", unit_price=100, total_amount=100),
            Booking(customer=cls.agent, provider=cls.nearby, booking_id="BK-ACTIVE",
                    status=Booking.Status.CONFIRMED, scheduled_date=cls.selected,
                    address="Farm", unit_price=100, total_amount=100),
            Booking(customer=cls.agent, booking_id="BK-CANCELLED", status=Booking.Status.CANCELLED,
                    scheduled_date=cls.selected, address="Farm", unit_price=100, total_amount=100),
        ])

    @classmethod
    def make_partner(cls, phone, name, gender="", longitude="0.02", **kwargs):
        user = User.objects.create(phone_number=phone, role=User.Role.PARTNER)
        CustomerProfile.objects.create(user=user, full_name=name, gender=gender)
        UserLocation.objects.create(user=user, latitude=0, longitude=Decimal(longitude))
        return PartnerProfile.objects.create(user=user, **kwargs)

    def setUp(self):
        self.client.force_login(self.agent)
        self.url = reverse("adminpanel:workers-by-date")

    def calendar_cell(self, response, day):
        return next(cell for week in response.context["calendar_weeks"] for cell in week
                    if cell and cell["day"] == day)

    def test_calendar_and_day_share_all_partner_filters_and_counts(self):
        for filters in [
            {}, {"type": "LABOR"}, {"gender": "F"}, {"skills": str(self.skill.pk)},
            {"skills": self.skill.name}, {"category": str(self.category.pk)},
            {"distance": "5"}, {"q": "Asha & Co"},
            {"type": "LABOR", "gender": "F", "skills": str(self.skill.pk), "distance": "5"},
        ]:
            with self.subTest(filters=filters):
                params = {"date": self.selected.isoformat(), **filters}
                month = self.client.get(self.url, {**params, "view": "calendar"})
                day = self.client.get(self.url, {**params, "view": "day"})
                self.assertEqual(month.status_code, 200)
                self.assertEqual(day.status_code, 200)
                cell = self.calendar_cell(month, self.selected.day)
                self.assertEqual(cell["free"], day.context["available_count"])
                self.assertEqual(cell["busy"], day.context["busy_count"])
                self.assertEqual(month.context["total_count"], day.context["total_count"])
        self.assertEqual(self.client.get(self.url).context["total_count"], 3)

    def test_distinct_partner_counts_and_global_bookings(self):
        response = self.client.get(self.url, {"date": self.selected, "view": "calendar"})
        cell = self.calendar_cell(response, self.selected.day)
        self.assertEqual((cell["free"], cell["busy"], cell["bookings"]), (2, 1, 2))
        for mode in ["calendar", "day"]:
            response = self.client.get(self.url, {"view": mode, "q": "no matching partner"})
            self.assertContains(response, "BK-PENDING")
            self.assertContains(response, "BK-ACTIVE")
            self.assertNotContains(response, "BK-CANCELLED")
            self.assertContains(response, "No partners found matching your filters.")

    def test_navigation_and_drilldown_preserve_encoded_filters(self):
        params = {"view": "calendar", "date": self.selected.isoformat(), "q": "Asha & Co",
                  "type": "LABOR", "gender": "F", "skills": self.skill.name,
                  "distance": "5", "sort": "wage_desc", "category": str(self.category.pk)}
        response = self.client.get(self.url, params)
        for key in ["previous_month_url", "next_month_url", "today_url"]:
            query = parse_qs(urlsplit(response.context[key]).query)
            for param, value in params.items():
                if param != "date":
                    self.assertEqual(query[param], [value])
        self.assertEqual(parse_qs(urlsplit(response.context["previous_month_url"]).query)["date"],
                         [f"{self.selected.year - 1}-12-15"])
        cell = self.calendar_cell(response, 20)
        day = self.client.get(self.url + cell["url"])
        self.assertEqual(day.context["view_mode"], "day")
        self.assertEqual(day.context["selected_date"].day, 20)
        self.assertEqual(day.context["search_q"], "Asha & Co")
        self.assertEqual(day.context["skills_filter"], self.skill.name)
        cleared = parse_qs(urlsplit(response.context["clear_advanced_url"]).query)
        self.assertEqual(cleared, {key: [params[key]] for key in ["view", "date", "type", "q"]})

    def test_defaults_legacy_links_and_invalid_input(self):
        self.assertEqual(self.client.get(self.url).context["view_mode"], "calendar")
        response = self.client.get(self.url, {"date": self.selected})
        self.assertEqual(response.context["view_mode"], "day")
        self.assertEqual(response.context["selected_date"], self.selected)
        for params in [
            {"date": "bad", "view": "bad", "category": "bad"},
            {"year": "bad", "month": "bad"}, {"year": "999999", "month": "99"},
        ]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 200)
        response = self.client.get(self.url, {"year": 2028, "month": 2, "view": "calendar"})
        self.assertEqual(sum(bool(cell) for week in response.context["calendar_weeks"] for cell in week), 29)

    def test_distance_at_zero_coordinates_and_day_sort(self):
        response = self.client.get(self.url, {"view": "day", "type": "LABOR", "distance": "5"})
        self.assertTrue(response.context["has_agent_location"])
        self.assertEqual([row["partner"] for row in response.context["partners_list"]], [self.nearby])
        response = self.client.get(self.url, {"view": "day", "type": "LABOR", "sort": "wage_asc"})
        self.assertEqual([row["partner"] for row in response.context["partners_list"]],
                         [self.distant, self.nearby])

    def test_dashboard_keeps_cards_without_calendar_or_booking_feed(self):
        response = self.client.get(reverse("adminpanel:dashboard"))
        for label in ["Total Users", "Partners", "Services", "Available Today", "Pending KYC"]:
            self.assertContains(response, label)
        self.assertEqual(response.context["available_today"], 3)
        self.assertNotContains(response, "BK-PENDING")
        self.assertNotIn("calendar_weeks", response.context)
        self.assertNotIn("pending_bookings", response.context)

    def test_customer_cannot_access_either_view(self):
        self.client.logout()
        for mode in ["calendar", "day"]:
            self.assertEqual(self.client.get(self.url, {"view": mode}).status_code, 302)
        customer = User.objects.create(phone_number="9000000005")
        self.client.force_login(customer)
        self.assertEqual(self.client.get(self.url).status_code, 302)
