from .models import Notification


def notification_context(request):
    if not request.user.is_authenticated:
        return {
            "unread_notification_count": 0,
        }

    return {
        "unread_notification_count": Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).count(),
    }


def pending_credential_disclosure(request):
    """
    Provide the first unacknowledged CredentialDisclosure for the
    logged-in moderator, so a popup can be rendered on any page.
    """
    from players.models import CredentialDisclosure

    if not request.user.is_authenticated:
        return {}

    role = getattr(request.user, "role", None)
    if role != "MODERATOR":
        return {}

    disclosure = (
        CredentialDisclosure.objects
        .filter(moderator=request.user, acknowledged_at__isnull=True)
        .select_related("player")
        .first()
    )

    return {"pending_credential_disclosure": disclosure}
