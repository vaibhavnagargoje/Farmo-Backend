"""Shared helpers for the admin panel: registration progress and phone lookup."""

import re

from django.urls import reverse
from labor_services.models import LaborDetails
from partners.models import PartnerProfile
from users.models import User


def normalize_phone(raw):
    """
    The 10-digit Indian mobile number the app stores (e.g. "9876543210"),
    accepting "+91 98765 43210", "09876543210" and similar. "" if invalid.
    """
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 and digits[0] in "6789" else ""


def find_user_by_phone(phone):
    """
    The user with this 10-digit number in any stored format ("9876543210",
    "+919876543210", ...), preferring an exact match. None if there is none.
    """
    candidates = [
        user for user in User.objects.filter(phone_number__endswith=phone)
        if normalize_phone(user.phone_number) == phone
    ]
    candidates.sort(key=lambda user: (user.phone_number != phone, user.date_joined))
    return candidates[0] if candidates else None


def _get_registration_progress(registration):
    partner_profile = registration.partner_profile
    if partner_profile is None:
        try:
            partner_profile = registration.registered_user.partner_profile
        except PartnerProfile.DoesNotExist:
            partner_profile = None

    has_partner_profile = bool(partner_profile)
    partner_type = registration.partner_type or (partner_profile.partner_type if partner_profile else None)
    has_labor_details = False

    if has_partner_profile and partner_type == PartnerProfile.PartnerType.LABOR:
        try:
            partner_profile.labor_details
            has_labor_details = True
        except LaborDetails.DoesNotExist:
            has_labor_details = False

    if not has_partner_profile:
        return {
            "status_label": "प्रोफाइल अपूर्ण",
            "status_tone": "amber",
            "action_label": "प्रोफाइल पूर्ण करा",
            "action_url": reverse(
                "adminpanel:create-worker-profile",
                kwargs={"user_id": registration.registered_user_id},
            ),
        }

    if partner_type == PartnerProfile.PartnerType.LABOR and not has_labor_details:
        return {
            "status_label": "कामगार तपशील अपूर्ण",
            "status_tone": "amber",
            "action_label": "तपशील पूर्ण करा",
            "action_url": reverse(
                "adminpanel:worker-details",
                kwargs={"user_id": registration.registered_user_id},
            ),
        }

    return {
        "status_label": "पूर्ण",
        "status_tone": "emerald",
        "action_label": "पाहा / अपडेट",
        "action_url": reverse(
            "adminpanel:registration-next",
            kwargs={"user_id": registration.registered_user_id},
        ),
    }
