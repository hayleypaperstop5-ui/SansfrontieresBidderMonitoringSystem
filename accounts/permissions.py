from .models import User


ADMIN_ROLES = (
    User.Role.ADMIN,
)

DIRECTOR_ROLES = (
    User.Role.ADMIN,
    User.Role.DIRECTOR,
)

MANAGER_ROLES = (
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.MANAGER,
)

MODERATION_ROLES = (
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.MANAGER,
    User.Role.MODERATOR,
)

MODERATOR_ROLES = (
    User.Role.MODERATOR,
)

ALL_ROLES = (
    User.Role.ADMIN,
    User.Role.DIRECTOR,
    User.Role.MANAGER,
    User.Role.MODERATOR,
    User.Role.BIDDER,
)

RATE_MANAGEMENT_ROLES = (
    User.Role.DIRECTOR,
)

