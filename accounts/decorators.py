from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*allowed_roles):
    """
    Allow access only to authenticated users whose role
    is included in allowed_roles.
    """

    def decorator(view_func):

        @wraps(view_func)
        @login_required(login_url="/login/")
        def wrapped_view(request, *args, **kwargs):
            if request.user.role not in allowed_roles:
                messages.error(
                    request,
                    "You do not have permission to access this page.",
                )
                return redirect("dashboard:home")

            return view_func(request, *args, **kwargs)

        return wrapped_view

    return decorator
