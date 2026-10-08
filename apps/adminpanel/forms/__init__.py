"""Stable imports for the feature modules in this package."""

from .widgets import (
    _apply,
    TEXT_ATTRS,
    TEXTAREA_ATTRS,
    FILE_ATTRS,
    SELECT_ATTRS,
)
from .users import (
    UserInfoForm,
    CustomerProfileAdminForm,
    UserLocationForm,
    AddUserForm,
)
from .partners import (
    PartnerProfileAdminForm,
    MachineryDetailsAdminForm,
    TransportDetailsAdminForm,
    LaborDetailsAdminForm,
)
from .services import (
    ServiceAdminForm,
    ServiceImageAdminForm,
)

__all__ = [
    '_apply',
    'TEXT_ATTRS',
    'TEXTAREA_ATTRS',
    'FILE_ATTRS',
    'SELECT_ATTRS',
    'UserInfoForm',
    'CustomerProfileAdminForm',
    'UserLocationForm',
    'AddUserForm',
    'PartnerProfileAdminForm',
    'MachineryDetailsAdminForm',
    'TransportDetailsAdminForm',
    'LaborDetailsAdminForm',
    'ServiceAdminForm',
    'ServiceImageAdminForm',
]
