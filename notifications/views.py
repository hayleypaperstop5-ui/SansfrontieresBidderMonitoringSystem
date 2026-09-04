from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.models import User

from .models import Notification


@login_required(login_url="/login/")
def notification_list(request):
    if request.user.role not in (
        User.Role.ADMIN,
        User.Role.DIRECTOR,
        User.Role.MANAGER,
    ):
        return render(
            request,
            "notifications/notification_list.html",
            {
                "notifications": [],
                "message": "You do not have permission to view Manager notifications.",
            },
        )

    notifications = Notification.objects.filter(
        recipient=request.user,
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
        },
    )
