from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from .decorators import role_required
from .models import User, StaffProfile
from .permissions import MANAGER_ROLES


@login_required
@role_required(*MANAGER_ROLES)
def staff_list(request):
    staff_profiles = (
        StaffProfile.objects
        .select_related("user")
        .filter(user__role=User.Role.MODERATOR)
        .order_by(
            "user__first_name",
            "user__last_name",
        )
    )

    return render(
        request,
        "accounts/staff_list.html",
        {
            "staff_profiles": staff_profiles,
        },
    )
