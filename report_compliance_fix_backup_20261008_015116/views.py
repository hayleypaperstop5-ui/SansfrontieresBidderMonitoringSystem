from django.shortcuts import redirect, render
from pathlib import Path
from django.contrib import messages
from django.contrib.auth import get_user_model

User = get_user_model()
from django.http import FileResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from payments.models import PaymentRecord

from accounts.models import User
from accounts.permissions import MANAGER_ROLES

from .forms import EndOfSessionReportForm
from .models import CoverageAlert, CoverageSession, ReportCompliance
from .services import (
    assign_coverage_session,
    finalize_morning_continuation,
    manager_override_end_coverage,
    request_replacement,
)


@login_required(login_url="/login/")

def moderator_coverage(request):
    """Moderator Shift & Coverage workspace."""

    if getattr(request.user, "role", None) != User.Role.MODERATOR:
        return redirect("dashboard:home")

    from .models import CoverageSession, EndOfSessionReport

    if request.method == "POST":
        action = request.POST.get("action")
        session_id = request.POST.get("session_id")

        session = None

        if session_id:
            session = (
                CoverageSession.objects
                .filter(
                    id=session_id,
                    moderator=request.user,
                )
                .select_related("player", "moderator")
                .first()
            )

        if action == "request_replacement" and session is not None:
            request_replacement(
                session=session,
                moderator=request.user,
            )
            messages.success(
                request,
                "Your replacement request has been submitted.",
            )
            return redirect("coverage:moderator_coverage")

    sessions = (
        CoverageSession.objects
        .filter(moderator=request.user)
        .select_related("player", "moderator")
        .order_by("-created_at", "-id")
    )

    active_session = (
        sessions
        .filter(status=CoverageSession.Status.ACTIVE)
        .first()
    )

    awaiting_report_session = (
        sessions
        .filter(
            status__in=(
                CoverageSession.Status.AWAITING_REPORT,
                CoverageSession.Status.HANDOVER,
            )
        )
        .first()
    )

    assigned_session = (
        sessions
        .filter(status=CoverageSession.Status.OPEN)
        .first()
    )

    expired_session = (
        sessions
        .filter(status=CoverageSession.Status.EXPIRED)
        .first()
    )

    return render(
        request,
        "coverage/moderator_coverage.html",
        {
            "active_session": active_session,
            "awaiting_report_session": awaiting_report_session,
            "assigned_session": assigned_session,
            "expired_session": expired_session,
        },
    )



@login_required(login_url="/login/")
def download_report_evidence(request, report_id):
    """
    Download the screenshot/evidence attached to an existing
    End-of-Session Report.

    Evidence is intentionally served through a protected endpoint rather
    than exposing the media file directly. Only management roles may
    download report evidence.
    """
    allowed_roles = {
        User.Role.MANAGER,
        User.Role.DIRECTOR,
        User.Role.ADMIN,
    }

    if request.user.role not in allowed_roles:
        return HttpResponseForbidden(
            "Only Managers, Directors and Administrators can download report evidence."
        )

    report = get_object_or_404(
        EndOfSessionReport.objects.select_related(
            "coverage_session",
            "player",
            "moderator",
        ),
        id=report_id,
    )

    if not report.screenshot:
        raise Http404("No evidence file is attached to this report.")

    try:
        evidence_file = report.screenshot.open("rb")
    except (FileNotFoundError, OSError):
        raise Http404("The evidence file could not be found.")

    filename = Path(report.screenshot.name).name

    return FileResponse(
        evidence_file,
        as_attachment=True,
        filename=filename,
    )

def end_of_session_report(request, session_id):
    if request.user.role not in [User.Role.DIRECTOR, User.Role.MANAGER, User.Role.MODERATOR, User.Role.ADMIN]:
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

            PaymentRecord.objects.create(
                moderator=request.user,
                coverage_session=session,
                chats_responded=report.chats_responded,
                payroll_processed_chats=0,
            )

            compliance = session.report_compliance
            submitted_at = report.submitted_at

            if submitted_at <= compliance.report_deadline:
                compliance.status = ReportCompliance.Status.COMPLETED_ON_TIME
            elif compliance.status == ReportCompliance.Status.OVERDUE:
                compliance.status = ReportCompliance.Status.LATE
            else:
                compliance.status = ReportCompliance.Status.LATE

            compliance.report = report
            compliance.report_submitted_at = submitted_at
            compliance.completed_at = submitted_at
            compliance.save(
                update_fields=[
                    'report',
                    'report_submitted_at',
                    'status',
                    'completed_at',
                    'updated_at',
                ]
            )

            session.status = CoverageSession.Status.COMPLETED
            session.save(update_fields=["status", "updated_at"])

            # Morning/day continuation:
            # after a successful report, create the new Day session once
            # the 09:00 hard boundary has been reached.
            continuation_session = finalize_morning_continuation(
                session=session,
                moment=timezone.localtime(),
            )

            if continuation_session is not None:
                messages.success(
                    request,
                    (
                        "Your End-of-Session Report has been submitted "
                        "successfully. Your continuation coverage session "
                        "has now started automatically."
                    ),
                )
                return HttpResponseRedirect(reverse("dashboard:home"))

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
    if request.user.role not in MANAGER_ROLES and request.user.role not in [User.Role.DIRECTOR, User.Role.ADMIN, 'DIRECTOR', 'ADMIN', 'SUPERUSER']:
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


@login_required
def coverage_opportunities(request):
    if getattr(request.user, "role", None) != "MODERATOR":
        return redirect("dashboard:home")
    from .self_application import get_coverage_opportunities
    return render(request, "coverage/opportunities.html", get_coverage_opportunities(request.user, timezone.localtime()))

@login_required
def apply_for_coverage(request, player_id):
    if request.method != "POST" or getattr(request.user, "role", None) != "MODERATOR":
        return redirect("coverage:opportunities")

    from .self_application import apply_for_player
    from .models import CoverageApplication

    opportunity_type = request.POST.get("opportunity_type", CoverageApplication.OpportunityType.NEW)

    try:
        winner, session, awarded = apply_for_player(
            request.user,
            player_id,
            opportunity_type,
            timezone.localtime(),
        )

        if awarded and winner.moderator_id == request.user.id:
            messages.success(
                request,
                "Coverage assignment successful. You have been signed in automatically and your coverage session is now ACTIVE.",
            )
            return redirect("dashboard:home")

        messages.info(
            request,
            "Your application was recorded. Another eligible moderator was awarded this opportunity.",
        )

    except Exception as exc:
        messages.error(request, str(exc))

    return redirect("coverage:opportunities")



