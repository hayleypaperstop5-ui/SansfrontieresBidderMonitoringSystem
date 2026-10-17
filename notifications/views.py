from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from .models import Notification


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(
        recipient=request.user
    ).select_related(
        "shift",
        "shift__player",
        "shift__actual_worker",
    )

    return render(
        request,
        "notifications/notification_list.html",
        {
            "notifications": notifications,
            "unread_notification_count": notifications.filter(
                is_read=False
            ).count(),
        },
    )


@login_required
@require_POST
def mark_as_read(request, notification_id):
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient=request.user,
    )

    if not notification.is_read:
        notification.is_read = True
        notification.save(update_fields=["is_read"])

    return HttpResponseRedirect(
        request.META.get(
            "HTTP_REFERER",
            "/notifications/",
        )
    )

@login_required
@require_GET
def notification_status(request):
    """
    Return unread notifications for the logged-in user.

    This endpoint is used by the browser alert engine.
    """

    notifications = list(
        Notification.objects.filter(
            recipient=request.user,
            is_read=False,
        ).order_by("-created_at")[:10]
    )

    return JsonResponse(
        {
            "unread_count": len(notifications),
            "notifications": [
                {
                    "id": notification.id,
                    "title": notification.title,
                    "message": notification.message,
                    "notification_type": notification.notification_type,
                    "alert_level": notification.alert_level,
                    "created_at": notification.created_at.isoformat(),
                }
                for notification in notifications
            ],
        }
    )

