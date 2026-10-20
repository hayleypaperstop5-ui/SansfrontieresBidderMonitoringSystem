from django.db import transaction
from django.db.models import Q
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
from .models import CoverageAlert, CoverageSession, EndOfSessionReport, ReportCompliance
from .services import (
    assign_coverage_session,
    create_report_compliance,
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

        if action == "request_replacement":
            if session is None:
                # Fallback: use the user's active session
                session = CoverageSession.objects.filter(
                    moderator=request.user,
                    status="ACTIVE",
                ).first()
            if session is None:
                messages.error(request, "No active session found.")
                return redirect("coverage:moderator_coverage")
            try:
                request_replacement(
                    session=session,
                    moderator=request.user,
                )
                messages.success(
                    request,
                    "Your replacement request has been submitted.",
                )
            except Exception as exc:
                messages.error(
                    request,
                    f"Could not request replacement: {exc}",
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
            with transaction.atomic():
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

                # Use the existing authoritative compliance service.
                # This safely creates the compliance record when a valid
                # AWAITING_REPORT session does not already have one.
                compliance = create_report_compliance(
                    session=session,
                    signed_out_at=session.signed_out_at,
                )

                submitted_at = report.submitted_at

                if submitted_at <= compliance.report_deadline:
                    compliance.status = ReportCompliance.Status.COMPLETED_ON_TIME
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

    # Build sets of already-assigned moderators and covered players.
    # Combine OPEN (manager-assigned, awaiting sign-in) and ACTIVE/HANDOVER
    # (currently covering) sessions so both dropdowns exclude in-use entries.
    _live_sessions = CoverageSession.objects.filter(
        status__in=(
            CoverageSession.Status.ACTIVE,
            CoverageSession.Status.HANDOVER,
            CoverageSession.Status.REPLACEMENT_REQUESTED,
        )
    )

    assigned_player_ids = set(
        open_assignments.values_list("player_id", flat=True)
    ) | set(
        _live_sessions.values_list("player_id", flat=True)
    )

    assigned_moderator_ids = set(
        open_assignments.values_list("moderator_id", flat=True)
    ) | set(
        _live_sessions.values_list("moderator_id", flat=True)
    )

    active_players = (
        Player.objects
        .filter(status=Player.Status.ACTIVE)
        .order_by("player_number")
    )

    # Build a set of moderators with outstanding reports (AWAITING_REPORT status).
    # These are excluded from the "Assign Player Coverage" dropdown because the
    # service (assign_coverage_session) will reject them anyway.
    awaiting_report_moderator_ids = set(
        CoverageSession.objects
        .filter(status=CoverageSession.Status.AWAITING_REPORT)
        .values_list("moderator_id", flat=True)
    )

    excluded_moderator_ids = assigned_moderator_ids | awaiting_report_moderator_ids

    available_eligible_moderators = (
        User.objects
        .filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        )
        .exclude(id__in=excluded_moderator_ids)
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

    # Replacement requests: sessions where the moderator has asked for a replacement
    # but the player is still covered (Option B: status stays ACTIVE, flag is set).
    # These are NOT coverage alerts (the player is covered) but managers need to see them.
    replacement_request_sessions = (
        CoverageSession.objects
        .select_related("player", "moderator")
        .filter(
            replacement_requested_at__isnull=False,
        )
        .filter(
            Q(status__in=(
                CoverageSession.Status.ACTIVE,
                CoverageSession.Status.REPLACEMENT_REQUESTED,
            ))
        )
        .order_by("-replacement_requested_at")
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
                CoverageSession.Status.HANDOVER,
                CoverageSession.Status.REPLACEMENT_REQUESTED,
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

    history_date = request.GET.get("history_date", "").strip()
    history_player = request.GET.get("history_player", "").strip()
    history_moderator = request.GET.get("history_moderator", "").strip()
    history_session = request.GET.get("history_session", "").strip()
    history_status = request.GET.get("history_status", "").strip()

    coverage_history = (
        CoverageSession.objects
        .select_related(
            "player",
            "moderator",
        )
        .all()
        .order_by("-operating_date", "-created_at", "-id")
    )

    if history_date:
        coverage_history = coverage_history.filter(
            operating_date=history_date
        )

    if history_player:
        coverage_history = coverage_history.filter(
            player_id=history_player
        )

    if history_moderator:
        coverage_history = coverage_history.filter(
            moderator_id=history_moderator
        )

    if history_session:
        coverage_history = coverage_history.filter(
            session_type=history_session
        )

    if history_status:
        coverage_history = coverage_history.filter(
            status=history_status
        )

    history_players = (
        Player.objects
        .filter(coverage_sessions__isnull=False)
        .distinct()
        .order_by("player_number")
    )

    history_moderators = (
        User.objects
        .filter(
            role=User.Role.MODERATOR,
            coverage_sessions__isnull=False,
        )
        .distinct()
        .order_by("first_name", "last_name", "email")
    )

    history_session_types = CoverageSession.SessionType.choices
    history_statuses = CoverageSession.Status.choices
    return render(
        request,
        "coverage/manager_alerts.html",
        {
        "replacement_request_sessions": replacement_request_sessions,
            "alerts": alerts,
            "active_sessions": active_sessions,
            "open_assignments": open_assignments,
            "available_players": available_players,
            "available_eligible_moderators": available_eligible_moderators,
            "available_moderators": available_moderators,
            "assigned_moderators": assigned_moderators,
            "coverage_history": coverage_history,
            "history_date": history_date,
            "history_player": history_player,
            "history_moderator": history_moderator,
            "history_session": history_session,
            "history_status": history_status,
            "history_players": history_players,
            "history_moderators": history_moderators,
            "history_session_types": history_session_types,
            "history_statuses": history_statuses,
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

@login_required
@login_required
def respond_to_continuation(request, session_id, response):
    """
    Handle the moderator's YES/NO response to a continuation prompt.
    POST-only. URL: /coverage/continuation/<session_id>/respond/<yes|no>/
    """
    from django.http import JsonResponse
    from .models import CoverageSession
    from .services import respond_to_coverage_continuation

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    if getattr(request.user, "role", None) != "MODERATOR":
        return JsonResponse({"error": "Moderator only"}, status=403)

    session = (
        CoverageSession.objects
        .filter(id=session_id, moderator=request.user, status="CONTINUATION_PENDING")
        .first()
    )
    if not session:
        return JsonResponse({"error": "No pending continuation for this session"}, status=404)

    response_upper = (response or "").upper()
    if response_upper not in ("YES", "NO"):
        return JsonResponse({"error": "response must be yes or no"}, status=400)

    try:
        respond_to_coverage_continuation(
            session=session,
            moderator=request.user,
            response=response_upper,
            moment=timezone.localtime(),
        )
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    if response_upper == "NO":
        redirect_url = reverse("coverage:end_of_session_report", args=[session.id])
    else:
        if session.session_type == "DAY":
            redirect_url = reverse("coverage:end_of_session_report", args=[session.id])
        else:
            redirect_url = "/dashboard/"

    return JsonResponse({
        "status": "success",
        "response": response_upper,
        "session_status": session.status,
        "redirect_url": redirect_url,
    })


def acknowledge_credential(request, disclosure_id):
    """
    Mark a CredentialDisclosure as acknowledged by its recipient.

    Only the moderator who is the recipient of the disclosure can
    acknowledge it. Returns a JSON response suitable for the popup's
    fetch() call.
    """
    from django.http import JsonResponse
    from django.utils import timezone as tz
    from players.models import CredentialDisclosure

    if request.method != "POST":
        return JsonResponse({"error": "POST required"}, status=405)

    try:
        disclosure = CredentialDisclosure.objects.get(
            id=disclosure_id,
            moderator=request.user,
        )
    except CredentialDisclosure.DoesNotExist:
        return JsonResponse({"error": "not found"}, status=404)

    if disclosure.acknowledged_at is None:
        disclosure.acknowledged_at = tz.now()
        disclosure.save(update_fields=["acknowledged_at"])

    # Transition the linked session from OPEN to ACTIVE (acknowledgement = sign-in)
    session = disclosure.coverage_session
    was_open = session is not None and session.status == "OPEN"
    if was_open:
        session.status = "ACTIVE"
        session.signed_in_at = tz.now()
        session.sign_in_deadline_at = None
        session.save(update_fields=["status", "signed_in_at", "sign_in_deadline_at"])

    # Notify management when a manager-assigned moderator successfully signs in.
    # This gives the manager confirmation that the assignment is live.
    if was_open:
        try:
            from coverage.services import _notify_management_team
            from notifications.models import Notification as _Notif
            moderator_name = (
                disclosure.moderator.get_full_name()
                or disclosure.moderator.username
            )
            _notify_management_team(
                title="Moderator Signed In",
                message=(
                    f"{moderator_name} has acknowledged the credentials and "
                    f"signed in to cover {disclosure.player}. "
                    f"Session {session.session_code or session.id} is now ACTIVE."
                ),
                alert_level=_Notif.AlertLevel.IMPORTANT,
            )
        except Exception:
            # Never block the acknowledge response on notification failure
            pass

    return JsonResponse({
        "ok": True,
        "disclosure_id": disclosure.id,
        "acknowledged_at": disclosure.acknowledged_at.isoformat(),
        "session_status": session.status if session else None,
    })

@login_required
def player_credentials_view(request, player_id):
    """
    Read-only view of the player's login credentials for a moderator
    who is CURRENTLY covering that player.

    Management roles can also view this page for any player.
    """
    from players.models import Player

    try:
        player = Player.objects.get(pk=player_id)
    except Player.DoesNotExist:
        messages.error(request, "Player not found.")
        return redirect("dashboard:home")

    role = getattr(request.user, "role", None)
    is_management = role in ("MANAGER", "DIRECTOR", "ADMIN")

    if not is_management:
        # Moderators can only see credentials for a player they currently cover.
        has_active_session = CoverageSession.objects.filter(
            player=player,
            moderator=request.user,
        ).filter(
            # Active/Handover sessions, OR any session with a replacement flag
            (
                Q(status__in=(
                    CoverageSession.Status.ACTIVE,
                    CoverageSession.Status.HANDOVER,
                ))
                | Q(replacement_requested_at__isnull=False)
            ),
        ).exists()

        if not has_active_session:
            messages.error(
                request,
                "You can only view credentials for a player you are currently covering.",
            )
            return redirect("dashboard:home")

    if not (player.login_username or player.login_password_encrypted):
        messages.info(request, f"{player} does not have login credentials on file.")
        return redirect("dashboard:home")

    return render(
        request,
        "coverage/player_credentials.html",
        {
            "player": player,
        },
    )


@login_required
def assign_replacement_view(request):
    """
    Manager/Director assigns a replacement moderator to a session with
    a pending replacement request. The replacement moderator's session
    starts as OPEN with a 15-min sign-in window (acknowledge credentials).
    The outgoing moderator is signed out to HANDOVER and must submit a report.
    """
    from .models import CoverageSession
    from .services import assign_replacement

    if request.method != "POST":
        messages.error(request, "POST required.")
        return redirect("coverage:manager_coverage_alerts")

    role = getattr(request.user, "role", None)
    if role not in ("MANAGER", "DIRECTOR", "ADMIN"):
        messages.error(request, "Only managers, directors, or admins can assign replacements.")
        return redirect("coverage:manager_coverage_alerts")

    action = request.POST.get("action")
    session_id = request.POST.get("session_id")
    replacement_moderator_id = request.POST.get("replacement_moderator_id")

    if action != "assign_replacement":
        messages.error(request, "Invalid action.")
        return redirect("coverage:manager_coverage_alerts")

    if not session_id or not replacement_moderator_id:
        messages.error(request, "Session and replacement moderator are required.")
        return redirect("coverage:manager_coverage_alerts")

    session = CoverageSession.objects.filter(id=session_id).first()
    if session is None:
        messages.error(request, "Session not found.")
        return redirect("coverage:manager_coverage_alerts")

    from accounts.models import User
    replacement_moderator = User.objects.filter(
        id=replacement_moderator_id,
        role=User.Role.MODERATOR,
        is_active=True,
    ).first()
    if replacement_moderator is None:
        messages.error(request, "Replacement moderator not found or not eligible.")
        return redirect("coverage:manager_coverage_alerts")

    try:
        new_session = assign_replacement(
            session=session,
            replacement_moderator=replacement_moderator,
            moment=timezone.localtime(),
        )
    except Exception as exc:
        messages.error(request, f"Could not assign replacement: {exc}")
        return redirect("coverage:manager_coverage_alerts")

    moderator_name = (
        replacement_moderator.get_full_name()
        or replacement_moderator.username
    )
    messages.success(
        request,
        f"{moderator_name} has been assigned as the replacement. "
        "They must acknowledge the credential popup within 15 minutes. "
        "If they do not acknowledge, the assignment will be marked MISSED "
        "and the Player will be released for reassignment.",
    )
    return redirect("coverage:manager_coverage_alerts")


@login_required
def my_reports(request):
    """
    List all End-of-Session Reports submitted by the logged-in moderator.
    Shows date, player, session, chats, rating, and evidence download link.
    """
    from .models import EndOfSessionReport
    from django.utils import timezone

    reports = (
        EndOfSessionReport.objects
        .filter(coverage_session__moderator=request.user)
        .select_related("coverage_session", "coverage_session__player")
        .order_by("-submitted_at", "-id")
    )

    return render(
        request,
        "coverage/my_reports.html",
        {
            "reports": reports,
            "total_reports": reports.count(),
        },
    )

