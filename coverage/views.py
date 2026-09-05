from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from accounts.models import User
from accounts.permissions import MANAGER_ROLES

from .models import CoverageAlert, CoverageSession
from .services import manager_override_end_coverage


@login_required(login_url="/login/")
def manager_coverage_alerts(request):
    if request.user.role not in MANAGER_ROLES:
        return HttpResponseForbidden(
            "You do not have permission to access coverage alerts."
        )

    if request.method == "POST":
        action = request.POST.get("action")
        session_id = request.POST.get("session_id")

        if action == "manager_override_end":
            session = get_object_or_404(
                CoverageSession,
                id=session_id,
            )

            try:
                manager_override_end_coverage(
                    session=session,
                    manager=request.user,
                )
            except Exception as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Manager override completed for {session.player}.",
                )

            return HttpResponseRedirect(
                reverse("coverage:manager_coverage_alerts")
            )

    alerts = (
        CoverageAlert.objects
        .select_related("player", "acknowledged_by", "resolved_by")
        .filter(
            status__in=(
                CoverageAlert.Status.OPEN,
                CoverageAlert.Status.ACKNOWLEDGED,
                CoverageAlert.Status.ESCALATED,
            )
        )
        .order_by("-created_at")
    )

    active_sessions = (
        CoverageSession.objects
        .select_related(
            "player",
            "moderator",
            "replacement_moderator",
        )
        .filter(
            status__in=(
                CoverageSession.Status.ACTIVE,
                CoverageSession.Status.REPLACEMENT_REQUESTED,
                CoverageSession.Status.HANDOVER,
            )
        )
        .order_by("player__player_number", "-signed_in_at")
    )

    return render(
        request,
        "coverage/manager_alerts.html",
        {
            "alerts": alerts,
            "active_sessions": active_sessions,
        },
    )
