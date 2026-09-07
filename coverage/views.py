from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from accounts.models import User
from accounts.permissions import MANAGER_ROLES

from .forms import EndOfSessionReportForm
from .models import CoverageAlert, CoverageSession
from .services import assign_coverage_session, manager_override_end_coverage


@login_required(login_url="/login/")
def end_of_session_report(request, session_id):
    if request.user.role != User.Role.MODERATOR:
        return HttpResponseForbidden(
            "Only Moderators can submit an End-of-Session Report."
        )

    session = get_object_or_404(
        CoverageSession.objects.select_related(
            "player",
            "moderator",
        ),
        id=session_id,
    )

    if session.moderator != request.user:
        messages.error(
            request,
            "You can only submit a report for your own coverage session.",
        )
        return HttpResponseRedirect(reverse("dashboard:home"))

    if not session.signed_in_at:
        messages.error(
            request,
            "You cannot submit an End-of-Session Report before signing in.",
        )
        return HttpResponseRedirect(reverse("dashboard:home"))

    if not session.signed_out_at:
        messages.error(
            request,
            "You must sign out of the coverage session before submitting the report.",
        )
        return HttpResponseRedirect(reverse("dashboard:home"))

    if hasattr(session, "end_of_session_report"):
        messages.info(
            request,
            "An End-of-Session Report has already been submitted for this session.",
        )
        return HttpResponseRedirect(reverse("dashboard:home"))

    if request.method == "POST":
        form = EndOfSessionReportForm(request.POST, request.FILES)

        if form.is_valid():
            report = form.save(commit=False)
            report.coverage_session = session
            report.moderator = request.user
            report.player = session.player
            report.save()

            session.status = CoverageSession.Status.COMPLETED
            session.save(update_fields=["status", "updated_at"])

            messages.success(
                request,
                "Your End-of-Session Report has been submitted successfully.",
            )
            return HttpResponseRedirect(reverse("dashboard:home"))
    else:
        form = EndOfSessionReportForm()

    return render(
        request,
        "coverage/end_of_session_report.html",
        {
            "form": form,
            "session": session,
        },
    )


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

        if action == "assign_coverage":
            moderator_id = request.POST.get("moderator_id")
            player_id = request.POST.get("player_id")

            moderator = get_object_or_404(
                User,
                id=moderator_id,
            )

            from players.models import Player

            player = get_object_or_404(
                Player,
                id=player_id,
            )

            try:
                session = assign_coverage_session(
                    manager=request.user,
                    moderator=moderator,
                    player=player,
                )
            except Exception as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"{moderator.get_full_name() or moderator.username} "
                    f"has been assigned to {player}. "
                    "The Moderator must sign in before coverage becomes active.",
                )

            return HttpResponseRedirect(
                reverse("coverage:manager_coverage_alerts")
            )

    from players.models import Player

    open_assignments = (
        CoverageSession.objects
        .select_related(
            "player",
            "moderator",
        )
        .filter(
            status=CoverageSession.Status.OPEN,
        )
        .order_by("player__player_number", "-created_at")
    )

    assigned_player_ids = set(
        open_assignments.values_list("player_id", flat=True)
    )

    assigned_moderator_ids = set(
        open_assignments.values_list("moderator_id", flat=True)
    )

    active_players = (
        Player.objects
        .filter(status=Player.Status.ACTIVE)
        .order_by("player_number")
    )

    available_eligible_moderators = (
        User.objects
        .filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        )
        .exclude(id__in=assigned_moderator_ids)
        .order_by("first_name", "last_name", "username")
    )

    available_players = active_players.exclude(
        id__in=assigned_player_ids,
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

    assigned_moderator_coverage = {}

    for session in open_assignments:
        assigned_moderator_coverage[session.moderator_id] = {
            "moderator": session.moderator,
            "player": session.player,
            "status": "Awaiting Sign-in",
        }

    for session in active_sessions:
        assigned_moderator_coverage[session.moderator_id] = {
            "moderator": session.moderator,
            "player": session.player,
            "status": session.get_status_display(),
        }

    eligible_moderators = (
        User.objects
        .filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        )
        .select_related("staff_profile")
        .order_by("first_name", "last_name", "username")
    )

    available_moderators = []
    assigned_moderators = []

    for moderator in eligible_moderators:
        coverage = assigned_moderator_coverage.get(moderator.id)

        if coverage is not None:
            assigned_moderators.append(
                {
                    "moderator": moderator,
                    "player": coverage["player"],
                    "coverage_status": coverage["status"],
                }
            )
        else:
            available_moderators.append(
                {
                    "moderator": moderator,
                    "coverage_status": "Available",
                }
            )

    return render(
        request,
        "coverage/manager_alerts.html",
        {
            "alerts": alerts,
            "active_sessions": active_sessions,
            "open_assignments": open_assignments,
            "available_players": available_players,
            "available_eligible_moderators": available_eligible_moderators,
            "available_moderators": available_moderators,
            "assigned_moderators": assigned_moderators,
        },
    )
