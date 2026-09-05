from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from accounts.decorators import role_required
from accounts.models import User
from accounts.permissions import ADMIN_ROLES
from shifts.models import Shift


@login_required
def dashboard(request):
    return render(
        request,
        "dashboard/dashboard.html",
    )


@role_required(*ADMIN_ROLES)
def admin_test(request):
    return render(
        request,
        "dashboard/admin_test.html",
    )


@login_required(login_url="/login/")
def my_shifts(request):
    if request.user.role != User.Role.MODERATOR:
        return render(
            request,
            "dashboard/my_shifts.html",
            {
                "shifts": [],
                "message": "My Shifts is available to Moderators only.",
            },
        )

    from django.db.models import Q

    shifts = Shift.objects.filter(
        Q(primary_moderator=request.user) |
        Q(substitute=request.user)
    ).select_related(
        "player",
        "primary_moderator",
        "substitute",
        "actual_worker",
    ).order_by(
        "-date",
        "scheduled_start",
    )

    return render(
        request,
        "dashboard/my_shifts.html",
        {
            "shifts": shifts,
        },
    )
