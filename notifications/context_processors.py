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

def pending_continuation_prompt(request):
    """
    Provide the first CONTINUATION_PENDING coverage session for the logged-in
    moderator, so a continuation YES/NO popup can be rendered on any page.
    """
    from coverage.models import CoverageSession

    if not request.user.is_authenticated:
        return {}

    role = getattr(request.user, "role", None)
    if role != "MODERATOR":
        return {}

    session = (
        CoverageSession.objects
        .filter(
            moderator=request.user,
            status="CONTINUATION_PENDING",
            continuation_prompted_at__isnull=False,
            continuation_response="",
        )
        .select_related("player")
        .order_by("-continuation_prompted_at")
        .first()
    )

    return {"pending_continuation_prompt": session}

def current_year(request):
    """Provide the current year to every template (e.g., for footers)."""
    from django.utils import timezone
    return {"current_year": timezone.localtime().year}

