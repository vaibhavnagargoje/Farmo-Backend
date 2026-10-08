"""Existing admin panel access and role-change permission rules."""

from users.models import User


def is_agent(user):
    """Admin, SuperAdmin, and Verification Manager can all access the panel."""
    if not user.is_authenticated:
        return False
    return user.is_staff or user.is_superuser or user.role in {
        User.Role.ADMIN,
        User.Role.SUPERADMIN,
        User.Role.MANAGER,
    }


def _get_actor_role(actor):
    """Resolve effective role: is_superuser maps to SUPERADMIN."""
    if actor.is_superuser:
        return User.Role.SUPERADMIN
    return actor.role


def get_allowed_role_targets(actor, target_user):
    """
    Return a set of Role *values* (strings) the actor may assign to target_user.

    Permission matrix:
      SuperAdmin  → any role on any user
      Admin       → CUSTOMER → {CUSTOMER, PARTNER}
                     MANAGER  → {MANAGER, ADMIN}
                     (cannot touch PARTNER, ADMIN, or SUPERADMIN targets)
      Manager     → CUSTOMER → {CUSTOMER, PARTNER}
                     (cannot touch any other target role)
    """
    actor_role = _get_actor_role(actor)
    target_role = target_user.role

    if actor_role == User.Role.SUPERADMIN:
        return {val for val, _ in User.Role.choices}

    if actor_role == User.Role.ADMIN:
        if target_role == User.Role.CUSTOMER:
            return {User.Role.CUSTOMER, User.Role.PARTNER}
        if target_role == User.Role.MANAGER:
            return {User.Role.MANAGER, User.Role.ADMIN}
        # PARTNER / ADMIN / SUPERADMIN targets — cannot touch
        return set()

    if actor_role == User.Role.MANAGER:
        if target_role == User.Role.CUSTOMER:
            return {User.Role.CUSTOMER, User.Role.PARTNER}
        return set()

    return set()


def get_allowed_role_choices(actor, target_user):
    """Filtered (value, label) pairs for the role dropdown in the template."""
    allowed_values = get_allowed_role_targets(actor, target_user)
    return [(val, label) for val, label in User.Role.choices if val in allowed_values]


def _can_toggle_active(actor, target_user):
    """
    Returns True if actor may flip the is_active flag on target_user.
      SuperAdmin  → anyone
      Admin       → anyone EXCEPT SuperAdmin accounts
      Manager     → nobody
    """
    actor_role = _get_actor_role(actor)
    if actor_role == User.Role.SUPERADMIN:
        return True
    if actor_role == User.Role.ADMIN:
        return target_user.role != User.Role.SUPERADMIN
    return False
