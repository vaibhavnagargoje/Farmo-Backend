"""Stable imports for the feature modules in this package."""

from ..permissions import (
    is_agent,
    _get_actor_role,
    get_allowed_role_targets,
    get_allowed_role_choices,
    _can_toggle_active,
)
from ..helpers import (
    _get_registration_progress,
)
from .auth import (
    get_client_ip,
    panel_login,
    panel_logout,
    rate_limited_django_admin_login,
    MAX_LOGIN_ATTEMPTS,
    LOCKOUT_TIME,
    original_django_admin_login,
)
from .dashboard import (
    dashboard,
)
from .map import (
    map_view,
    map_data,
    map_message_draft,
    map_assign_partner,
    map_cancel_booking,
    map_complete_booking,
)
from .users import (
    users_list,
    add_user,
    _build_user_detail_context,
    user_detail,
    update_user_info,
    update_customer_profile,
    update_user_location,
)
from .partners import (
    update_partner_profile,
    update_labor_details,
    update_machinery_details,
    update_transport_details,
)
from .services import (
    service_create,
    service_edit,
    service_image_upload,
    service_image_delete,
)
from .availability import (
    agent_worker_calendar,
    agent_toggle_busy_day,
    agent_workers_by_date,
)
from .bookings import (
    agent_worker_booking_action,
)

__all__ = [
    'is_agent',
    '_get_actor_role',
    'get_allowed_role_targets',
    'get_allowed_role_choices',
    '_can_toggle_active',
    '_get_registration_progress',
    'get_client_ip',
    'panel_login',
    'panel_logout',
    'rate_limited_django_admin_login',
    'MAX_LOGIN_ATTEMPTS',
    'LOCKOUT_TIME',
    'original_django_admin_login',
    'dashboard',
    'map_view',
    'map_data',
    'map_message_draft',
    'map_assign_partner',
    'map_cancel_booking',
    'map_complete_booking',
    'users_list',
    'add_user',
    '_build_user_detail_context',
    'user_detail',
    'update_user_info',
    'update_customer_profile',
    'update_user_location',
    'update_partner_profile',
    'update_labor_details',
    'update_machinery_details',
    'update_transport_details',
    'service_create',
    'service_edit',
    'service_image_upload',
    'service_image_delete',
    'agent_worker_calendar',
    'agent_toggle_busy_day',
    'agent_workers_by_date',
    'agent_worker_booking_action',
]
