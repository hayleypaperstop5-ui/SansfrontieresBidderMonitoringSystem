from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db import models
from django.db.models import Count, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from accounts.decorators import role_required
from accounts.forms import StaffSelfProfileForm
from accounts.models import StaffProfile, User
from accounts.permissions import ADMIN_ROLES
from accounts.utils import normalize_whatsapp_number
from bonuses.models import BonusAward
from coverage.forms import ContinuationResponseForm
from coverage.models import CoverageSession
from coverage.services import (
    close_expired_coverage_sessions,
    request_replacement,
    respond_to_coverage_continuation,
)
from payments.models import ModeratorPayment, PaymentRecord, PaymentSettings
from payments.services import (
    calculate_gross_amount,
    get_applicable_rate_tier,
    get_player_payment_threshold,
    process_thursday_payroll,
)
from players.models import Player



def _get_moderator_weekly_earnings(user, weeks=8):
    """
    Return the moderator's earnings per payroll week for the last N weeks.
    """
    from payments.models import ModeratorPayment
    from django.utils import timezone

    runs = list(ModeratorPayment.objects.filter(
        moderator=user,
    ).order_by('-payment_week_start')[:weeks])

    weeks_data = []
    for i, run in enumerate(runs):
        weeks_data.append({
            "week_start": run.payment_week_start.strftime("%d %b") if run.payment_week_start else "—",
            "week_end": run.payment_week_end.strftime("%d %b") if run.payment_week_end else "—",
            "label": run.payment_week_start.strftime("%d %b") if run.payment_week_start else f"W-{weeks-1-i}",
            "earned": float(run.earned_amount or 0),
            "chats": run.payable_chats or 0,
            "is_current": (i == 0),
        })
    weeks_data.reverse()

    last_week = weeks_data[-2] if len(weeks_data) >= 2 else None
    current = weeks_data[-1] if weeks_data else None
    non_current = weeks_data[:-1]
    average = (sum(w["earned"] for w in weeks_data) / len(weeks_data)) if weeks_data else 0

    trend = "stable"
    if len(non_current) >= 2:
        prev = non_current[-2]["earned"]
        last = non_current[-1]["earned"]
        if last > prev * 1.10:
            trend = "up"
        elif last < prev * 0.90:
            trend = "down"

    return {
        "weeks": weeks_data,
        "last_week_earned": last_week["earned"] if last_week else 0,
        "last_week_label": last_week["label"] if last_week else "—",
        "current_earned": current["earned"] if current else 0,
        "current_label": current["label"] if current else "—",
        "average": round(average, 2),
        "trend": trend,
    }

def _get_moderator_weekly_chats(user):
    import json
    from django.utils import timezone
    from datetime import timedelta
    from coverage.models import EndOfSessionReport
    now = timezone.localtime()
    monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    sunday_end = monday + timedelta(days=7)
    reports = EndOfSessionReport.objects.filter(moderator=user, submitted_at__gte=monday, submitted_at__lt=sunday_end).values_list('submitted_at', 'chats_responded')
    daily = [0] * 7
    for submitted_at, chats in reports:
        local = timezone.localtime(submitted_at)
        daily[local.weekday()] += (chats or 0)
    labels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    total = sum(daily)
    days_active = sum(1 for d in daily if d > 0)
    best_idx = daily.index(max(daily)) if any(daily) else 0
    return {'labels': labels, 'moderator_name': user.get_full_name() or user.username, 'data': daily, 'total': total, 'days_active': days_active, 'best_day': labels[best_idx] if total > 0 else '-', 'best_day_chats': daily[best_idx] if total > 0 else 0}

def _get_weekly_moderator_chats():
    """
    Aggregate EndOfSessionReport.chats_responded by moderator and day-of-week
    for the current week (Mon -> Sun), in the user's local timezone.
    Multiple reports on the same day for the same moderator are SUMMED.
    """
    from django.utils import timezone
    from datetime import timedelta
    from coverage.models import EndOfSessionReport

    now = timezone.localtime()
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    sunday_end = monday + timedelta(days=7)

    reports = EndOfSessionReport.objects.filter(
        submitted_at__gte=monday,
        submitted_at__lt=sunday_end,
    ).select_related("moderator").values_list(
        "moderator__first_name",
        "moderator__last_name",
        "moderator__username",
        "submitted_at",
        "chats_responded",
    )

    daily = {}
    for first, last, username, submitted_at, chats in reports:
        name = f"{first} {last}".strip() or username
        if not name:
            continue
        local_submitted = timezone.localtime(submitted_at)
        weekday = local_submitted.weekday()
        if name not in daily:
            daily[name] = [0] * 7
        daily[name][weekday] += (chats or 0)

    sorted_mods = sorted(
        (n for n in daily.keys() if sum(daily[n]) > 0),
        key=lambda n: sum(daily[n]),
        reverse=True,
    )

    return {
        "labels": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
        "moderators": sorted_mods,
        "data": {m: daily[m] for m in sorted_mods},
    }

@login_required(login_url="/login/")
def dashboard(request):
    """
    Main dashboard.

    Moderators see the Moderator dashboard.
    Directors see the Director dashboard.
    Other roles are redirected to the normal dashboard/home route.
    """

    if request.user.role == User.Role.DIRECTOR:
        return director_dashboard(request)

    if request.user.role == User.Role.MANAGER:
        manager_reports = list(
            CoverageSession.objects
            .filter(
                end_of_session_report__isnull=False,
            )
            .select_related(
                "end_of_session_report",
                "player",
                "moderator",
            )
            .order_by(
                "-operating_date",
                "-end_of_session_report__submitted_at",
            )[:20]
        )

        return render(
            request,
            "dashboard/dashboard.html",
            {
                "manager_reports": manager_reports,
            },
        )

    if request.user.role != User.Role.MODERATOR:
        return render(
            request,
            "dashboard/dashboard.html",
        )

    moment = timezone.localtime()
    today = moment.date()

    close_expired_coverage_sessions(
        moment=moment,
    )

    coverage_sessions = (
        CoverageSession.objects
        .select_related(
            "player",
            "replacement_moderator",
        )
        .filter(
            moderator=request.user,
        )
        .order_by(
            "-operating_date",
            "-created_at",
        )
    )

    # Prefer an actually ACTIVE coverage session over an older
    # OPEN/waiting session. Self-application now signs the winning
    # moderator in automatically, so ACTIVE must be the authoritative
    # current coverage state.
    current_session = (
        coverage_sessions
        .filter(
            status=CoverageSession.Status.ACTIVE,
        )
        .order_by(
            "-signed_in_at",
            "-created_at",
            "-id",
        )
        .first()
    )

    # If there is no ACTIVE session, fall back to the normal pending/
    # handover/report states.
    if current_session is None:
        current_session = coverage_sessions.filter(
            status__in=(
                CoverageSession.Status.OPEN,
                CoverageSession.Status.REPLACEMENT_REQUESTED,
                CoverageSession.Status.HANDOVER,
                CoverageSession.Status.CONTINUATION_PENDING,
                CoverageSession.Status.AWAITING_REPORT,
            ),
        ).first()

    awaiting_reports = coverage_sessions.filter(
        status=CoverageSession.Status.AWAITING_REPORT,
    ).count()

    missed_sessions = coverage_sessions.filter(
        status__in=(
            CoverageSession.Status.EXPIRED,
            CoverageSession.Status.MISSED,
        ),
    ).count()

    replacement_requests = coverage_sessions.filter(
        status=CoverageSession.Status.REPLACEMENT_REQUESTED,
    ).count()

    reports = (
        coverage_sessions
        .filter(
            end_of_session_report__isnull=False,
        )
        .select_related(
            "end_of_session_report",
            "player",
        )
    )

    # "Chats Today" = calendar today's work (still useful for daily tracking).
    chats_today = sum(
        report.end_of_session_report.chats_responded
        for report in reports
        if report.operating_date == today
    )

    # "Chats This Week" — shown to the moderator as "chats since last payroll".
    # This is what actually matters to them: how much work is pending payment.
    # Implementation: count every report whose session has NOT been payroll-processed.
    # When payroll runs, payroll_processed_chats increases and these reports drop out.
    # The label in the template should reflect this — see the template fix below.
    from payments.models import PaymentRecord as _PR
    chats_since_last_payroll = 0
    _processed_session_ids = set(
        _PR.objects.filter(
            moderator=request.user,
            payroll_processed_chats__gte=models.F("chats_responded"),
        ).values_list("coverage_session_id", flat=True)
    )
    for _r in _PR.objects.filter(moderator=request.user).select_related("coverage_session"):
        # Skip fully processed payments
        if _r.coverage_session_id in _processed_session_ids:
            continue
        _unprocessed = (_r.chats_responded or 0) - (getattr(_r, "payroll_processed_chats", 0) or 0)
        if _unprocessed > 0:
            chats_since_last_payroll += _unprocessed

    # Keep `chats_this_week` as an alias so existing template variables still work,
    # but they now represent "unpaid chats" rather than "chats in the calendar week".
    chats_this_week = chats_since_last_payroll

    month_start = today.replace(day=1)

    chats_this_month = sum(
        report.end_of_session_report.chats_responded
        for report in reports
        if month_start <= report.operating_date <= today
    )

    recent_reports = list(reports[:5])

    payment_records = (
        PaymentRecord.objects
        .filter(
            moderator=request.user,
        )
        .order_by("-created_at")
    )

    moderator_payroll = (
        ModeratorPayment.objects
        .filter(
            moderator=request.user,
        )
        .order_by("-payment_week_end")
    )

    # Chats whose ModeratorPayment is fully PAID
    paid_chats = sum(
        (
            payment.payable_chats
            for payment in moderator_payroll
            if payment.status == ModeratorPayment.Status.PAID
        ),
        0,
    )

    # Chats whose ModeratorPayment is UNPAID or PARTIALLY_PAID
    unpaid_chats = sum(
        (
            payment.payable_chats
            for payment in moderator_payroll
            if payment.status in (
                ModeratorPayment.Status.UNPAID,
                ModeratorPayment.Status.PARTIALLY_PAID,
            )
        ),
        0,
    )

    payroll_earned = sum(
        (
            payment.earned_amount
            for payment in moderator_payroll
        ),
        Decimal("0.00"),
    )

    payroll_paid = sum(
        (
            payment.amount_paid
            for payment in moderator_payroll
        ),
        Decimal("0.00"),
    )

    payroll_outstanding = sum(
        (
            payment.outstanding_amount
            for payment in moderator_payroll
        ),
        Decimal("0.00"),
    )

    payroll_chat_earnings = sum(
        (
            payment.chat_earnings
            for payment in moderator_payroll
        ),
        Decimal("0.00"),
    )

    # Bonus earned: sum of BonusAward records in the current week (Mon-Sun).
    # Previously this read from ModeratorPayment.bonus_earned, which is 0 when
    # the award hasn't been linked to a payment record. Reading directly from
    # BonusAward is the authoritative source.
    from bonuses.models import BonusAward as _BonusAward
    week_start_date = today - timedelta(days=today.weekday())
    week_end_date = week_start_date + timedelta(days=6)

    week_bonus_awards = _BonusAward.objects.filter(
        moderator=request.user,
        bonus_date__gte=week_start_date,
        bonus_date__lte=week_end_date,
    )
    payroll_bonus_earned = sum(
        (award.bonus_amount for award in week_bonus_awards),
        Decimal("0.00"),
    )

    # Also compute total (all-time) bonus for reference
    all_bonus_awards = _BonusAward.objects.filter(moderator=request.user)
    total_bonus_earned = sum(
        (award.bonus_amount for award in all_bonus_awards),
        Decimal("0.00"),
    )

    current_rate = None

    try:
        applicable_rate_tier = get_applicable_rate_tier(
            chats_responded=chats_today,
            operating_date=today,
        )
    except Exception:
        applicable_rate_tier = None

    if applicable_rate_tier is not None:
        current_rate = applicable_rate_tier.rate_per_chat

    bonus_awards = BonusAward.objects.filter(
        moderator=request.user,
    )

    bonus_earned = sum(
        (
            award.bonus_amount
            for award in bonus_awards
        ),
        Decimal("0.00"),
    )

    # Compute unprocessed work value from PaymentRecords
    from payments.models import PaymentRecord as _PR
    from payments.services import get_applicable_rate_tier as _get_rate

    _unprocessed_value = Decimal("0.00")
    _unprocessed_chats = 0
    for _rec in _PR.objects.filter(moderator=request.user).select_related("coverage_session"):
        _chats = _rec.chats_responded or 0
        _processed = getattr(_rec, "payroll_processed_chats", 0) or 0
        _unproc = _chats - _processed
        if _unproc <= 0:
            continue
        _unprocessed_chats += _unproc
        try:
            _tier = _get_rate(
                chats_responded=_chats,
                operating_date=_rec.coverage_session.operating_date,
            )
            _rate = _tier.rate_per_chat if _tier else Decimal("3.46")
        except Exception:
            _rate = Decimal("3.46")
        _unprocessed_value += Decimal(str(_unproc)) * Decimal(str(_rate))    # Amount Earned: only counts PROCESSED payroll (ModeratorPayment records)
    # Work that hasn't been payroll-processed yet is tracked separately as "pending_payroll"
    total_earnings = payroll_earned
    amount_earned = payroll_earned
    paid_amount = payroll_paid
    # Outstanding: what the moderator is owed but hasn't been paid yet
    # Includes unprocessed work + unpaid payroll + unpaid bonus
    outstanding_amount = payroll_outstanding + _unprocessed_value
    bonus_earned = payroll_bonus_earned

    next_action = {
        "title": "You're all caught up",
        "message": (
            "No action is currently required. "
            "Keep up the good work."
        ),
        "button_label": None,
        "button_url": None,
        "tone": "success",
    }

    if current_session is not None:

        if current_session.status == CoverageSession.Status.OPEN:
            next_action = {
                "title": "Action Required",
                "message": (
                    "You have an assigned coverage session "
                    "waiting for sign-in."
                ),
                "button_label": "Sign In to Coverage",
                "button_url": "coverage:moderator_coverage",
                "tone": "warning",
            }

        elif current_session.status == CoverageSession.Status.CONTINUATION_PENDING:
            next_action = {
                "title": "Continuation Required",
                "message": (
                    "Your coverage continuation window is open. "
                    "Choose YES to continue covering the same Player "
                    "or NO to end this coverage session and submit your report."
                ),
                "button_label": "Respond to Continuation",
                "button_url": None,  # Popup handles the response — no redirect needed
                "tone": "warning",
            }

        elif (
            current_session.status
            == CoverageSession.Status.AWAITING_REPORT
        ):
            next_action = {
                "title": "Report Required",
                "message": (
                    "Your previous coverage session has ended. "
                    "Submit your end-of-session report."
                ),
                "button_label": "Submit Report",
                "button_url": "coverage:end_of_session_report",
                "button_args": [current_session.id],
                "tone": "warning",
            }

        elif (

            current_session.status == CoverageSession.Status.ACTIVE

            and getattr(current_session, "replacement_requested_at", None)

            is not None

        ):

            next_action = {

                "title": "Replacement Requested",

                "message": (

                    "Your replacement request has been sent. "

                    "Another eligible Moderator can now be assigned. "

                    "Keep covering the Player until the replacement "

                    "is confirmed. You will be signed out automatically "

                    "and required to submit your End-of-Session Report."

                ),

                "button_label": "Manage Coverage",

                "button_url": "coverage:moderator_coverage",

                "tone": "warning",

            }

        

        elif (
            current_session.status
            == CoverageSession.Status.REPLACEMENT_REQUESTED
        ):
            next_action = {
                "title": "Replacement Requested",
                "message": (
                    "Your replacement request has been sent. "
                    "Continue covering the Player until the "
                    "replacement is secured."
                ),
                "button_label": "Manage Coverage",
                "button_url": "coverage:moderator_coverage",
                "tone": "warning",
            }

        elif current_session.status in (
            CoverageSession.Status.ACTIVE,
            CoverageSession.Status.HANDOVER,
        ):
            next_action = {
                "title": "Coverage In Progress",
                "message": (
                    "You are currently responsible for this "
                    "Player coverage session."
                ),
                "button_label": "Manage Coverage",
                "button_url": "coverage:moderator_coverage",
                "tone": "success",
            }

    manager_contact = (
        StaffProfile.objects
        .select_related("user")
        .filter(
            user__role=User.Role.MANAGER,
            status=StaffProfile.Status.ACTIVE,
        )
        .first()
    )

    director_contact = (
        StaffProfile.objects
        .select_related("user")
        .filter(
            user__role=User.Role.DIRECTOR,
            status=StaffProfile.Status.ACTIVE,
        )
        .first()
    )

    if manager_contact:
        manager_contact.whatsapp_number = normalize_whatsapp_number(
            manager_contact.phone_number
        )

    if director_contact:
        director_contact.whatsapp_number = normalize_whatsapp_number(
            director_contact.phone_number
        )
    return render(
        request,
        "dashboard/dashboard.html",
        {
            "current_session": current_session,
            "awaiting_reports": awaiting_reports,
            "missed_sessions": missed_sessions,
            "replacement_requests": replacement_requests,
            "chats_today": chats_today,
            "chats_this_week": chats_this_week,
            "chats_this_month": chats_this_month,
            "recent_reports": recent_reports,
            "unpaid_chats": unpaid_chats,
            "amount_earned": amount_earned,
            "pending_payroll": _unprocessed_value,
            "anticipated_pay": _unprocessed_value,
            "unprocessed_chats": _unprocessed_chats,
            "paid_amount": paid_amount,
            "paid_chats": paid_chats,
            "outstanding_amount": outstanding_amount,
            "bonus_earned": bonus_earned,
            "total_earnings": total_earnings,
            "current_rate": current_rate,
            "next_action": next_action,
            "payment_count": payment_records.count(),
            "moderator_payroll": moderator_payroll,
            "payroll_earned": payroll_earned,
            "payroll_paid": payroll_paid,
            "payroll_outstanding": payroll_outstanding,
            "payroll_chat_earnings": payroll_chat_earnings,
            "payroll_bonus_earned": payroll_bonus_earned,
            "manager_contact": manager_contact,
            "director_contact": director_contact,
        },
    )

@role_required(User.Role.DIRECTOR)
def process_director_payroll(request):
    """
    Process the Director's weekly Moderator payroll action.

    Payroll processing is POST-only and is delegated to the payment
    service so the dashboard does not contain payroll business logic.
    """

    # Configuration and review must occur before payroll.
    return redirect("payments:payment_settings")

    if request.method != "POST":
        return redirect("dashboard:home")

    payment_date = timezone.localtime().date()

    try:
        result = process_thursday_payroll(
            payment_date=payment_date,
        )

        messages.success(
            request,
            (
                f"Weekly payroll processed successfully. "
                f"{result['payments_created']} Moderator payment record(s) "
                f"created."
            ),
        )

    except Exception as exc:
        messages.error(
            request,
            f"Weekly payroll could not be processed: {exc}",
        )

    return redirect("dashboard:home")

@role_required(User.Role.DIRECTOR)
def director_dashboard(request):
    from coverage.models import CoverageSession
    from players.models import Player
    """
    Director executive dashboard.

    This view is intentionally read-only for now.

    Configuration actions such as:
    - chat-rate management
    - staff management
    - player management
    - bonus management
    - payroll settings

    should be connected to the existing management views rather
    than creating duplicate configuration systems.
    """

    moment = timezone.localtime()
    today = moment.date()

    week_start = today - timedelta(days=today.weekday())

    # ---------------------------------------------------------
    # STAFF
    # ---------------------------------------------------------

    staff = User.objects.filter(staff_profile__isnull=False).distinct()

    active_staff = staff.filter(
        is_active=True,
    ).count()

    moderators = staff.filter(
        role=User.Role.MODERATOR,
    )

    active_moderators = moderators.filter(
        is_active=True,
    ).count()

    managers = staff.filter(
        role=User.Role.MANAGER,
    )

    active_managers = managers.filter(
        is_active=True,
    ).count()

    # ---------------------------------------------------------
    # PLAYERS
    # ---------------------------------------------------------

    total_players = Player.objects.count()

    active_players = Player.objects.filter(
        status=Player.Status.ACTIVE,
    ).count()

    inactive_players = Player.objects.filter(
        status=Player.Status.INACTIVE,
    ).count()

    # ---------------------------------------------------------
    # COVERAGE
    # ---------------------------------------------------------

    total_coverage_sessions = CoverageSession.objects.count()

    active_coverage_sessions = CoverageSession.objects.filter(
        status__in=(
            CoverageSession.Status.OPEN,
            CoverageSession.Status.ACTIVE,
            CoverageSession.Status.REPLACEMENT_REQUESTED,
            CoverageSession.Status.HANDOVER,
            CoverageSession.Status.AWAITING_REPORT,
        ),
    ).count()

    # ---------------------------------------------------------
    # CHAT VOLUME
    # ---------------------------------------------------------

    completed_reports = CoverageSession.objects.filter(
        end_of_session_report__isnull=False,
    ).select_related(
        "end_of_session_report",
        "player",
        "moderator",
    )

    total_chats = 0

    chats_this_week = 0

    chats_this_month = 0

    month_start = today.replace(day=1)

    for session in completed_reports:

        report = session.end_of_session_report

        chats = report.chats_responded or 0

        total_chats += chats

        if week_start <= session.operating_date <= today:
            chats_this_week += chats

        if month_start <= session.operating_date <= today:
            chats_this_month += chats

    # ---------------------------------------------------------
    # PAYROLL
    # ---------------------------------------------------------

    moderator_payroll = ModeratorPayment.objects.select_related(
        "moderator",
    )

    total_payment_records = moderator_payroll.count()

    generated_amount = sum(
        (payment.earned_amount for payment in moderator_payroll),
        Decimal("0.00"),
    )

    paid_amount = sum(
        (payment.amount_paid for payment in moderator_payroll),
        Decimal("0.00"),
    )

    outstanding_amount = sum(
        (payment.outstanding_amount for payment in moderator_payroll),
        Decimal("0.00"),
    )

    unpaid_payment_records = moderator_payroll.filter(
        status=ModeratorPayment.Status.UNPAID,
    ).count()

    paid_payment_records = moderator_payroll.filter(
        status=ModeratorPayment.Status.PAID,
    ).count()

    # ---------------------------------------------------------
    # BONUSES
    # ---------------------------------------------------------

    bonus_awards = BonusAward.objects.select_related(
        "moderator",
    )

    total_bonuses = sum(
        (
            award.bonus_amount
            for award in bonus_awards
        ),
        Decimal("0.00"),
    )

    weekly_bonuses = sum(
        (
            award.bonus_amount
            for award in bonus_awards
            if week_start <= award.bonus_date <= today
        ),
        Decimal("0.00"),
    )

    # ---------------------------------------------------------
    # CURRENT CHAT RATE
    # ---------------------------------------------------------

    current_rate_tier = None
    current_rate = None

    try:
        from players.models import PlayerChatRateTier
        from payments.services import get_applicable_player_chat_rate_tier
        from django.db.models import F, Sum as _Sum

        active_session = (
            CoverageSession.objects
            .filter(
                moderator=request.user,
                status=CoverageSession.Status.ACTIVE,
            )
            .select_related("player")
            .order_by("-signed_in_at")
            .first()
        )

        if active_session:
            # Rate based on the active session's player's total weekly chats
            player_week_chats = (
                PaymentRecord.objects
                .filter(
                    coverage_session__player=active_session.player,
                    coverage_session__operating_date__gte=today - timezone.timedelta(days=today.weekday() + 7),
                    coverage_session__operating_date__lte=today,
                )
                .aggregate(total=_Sum("chats_responded"))["total"]
                or 0
            )
            current_rate_tier = get_applicable_player_chat_rate_tier(
                player=active_session.player,
                chats_responded=player_week_chats,
                operating_date=today,
            )
        else:
            # No active session — show the highest rate tier for the current chat count
            current_rate_tier = get_applicable_rate_tier(
                chats_responded=chats_this_week,
                operating_date=today,
            )
    except Exception:
        current_rate_tier = None

    current_rate = (
        current_rate_tier.rate_per_chat
        if current_rate_tier
        else None
    )

    # ---------------------------------------------------------
    # MODERATOR PERFORMANCE
    # ---------------------------------------------------------

    moderator_performance = []

    for moderator in moderators:

        moderator_payroll_records = moderator_payroll.filter(
            moderator=moderator,
        )

        moderator_bonuses = bonus_awards.filter(
            moderator=moderator,
        )

        moderator_chats = sum(
            (
                payment.payable_chats
                for payment in moderator_payroll_records
            ),
            0,
        )

        moderator_gross = sum(
            (
                payment.earned_amount
                for payment in moderator_payroll_records
            ),
            Decimal("0.00"),
        )

        moderator_paid = sum(
            (
                payment.amount_paid
                for payment in moderator_payroll_records
            ),
            Decimal("0.00"),
        )

        moderator_outstanding = sum(
            (
                payment.outstanding_amount
                for payment in moderator_payroll_records
            ),
            Decimal("0.00"),
        )

        moderator_bonus = sum(
            (
                bonus.bonus_amount
                for bonus in moderator_bonuses
            ),
            Decimal("0.00"),
        )

        moderator_performance.append(
            {
                "moderator": moderator,
                "chats": moderator_chats,
                "gross": moderator_gross,
                "bonus": moderator_bonus,
                "paid": moderator_paid,
                "outstanding": moderator_outstanding,
            }
        )

    moderator_performance.sort(
        key=lambda item: item["gross"],
        reverse=True,
    )

    # ---------------------------------------------------------
    # PLAYER CHAT QUALIFICATION
    # ---------------------------------------------------------

    player_chat_threshold = get_player_payment_threshold(
        operating_date=today,
    )

    player_chat_totals = []

    unprocessed_payment_records = (
        PaymentRecord.objects
        .select_related(
            "coverage_session",
            "coverage_session__player",
        )
        .filter(
            coverage_session__operating_date__lte=today,
            chats_responded__gt=models.F("payroll_processed_chats"),
        )
        .order_by(
            "coverage_session__player_id",
            "id",
        )
    )

    player_unprocessed_chats = {}

    for payment_record in unprocessed_payment_records:
        player = payment_record.coverage_session.player
        unprocessed = (
            payment_record.chats_responded
            - payment_record.payroll_processed_chats
        )

        player_unprocessed_chats[player.id] = (
            player_unprocessed_chats.get(player.id, 0)
            + unprocessed
        )

    players = Player.objects.all()

    for player in players:
        player_chats = player_unprocessed_chats.get(
            player.id,
            0,
        )

        player_chat_totals.append(
            {
                "player": player,
                "chats": player_chats,
                "qualifies": player_chats >= player_chat_threshold,
                "remaining": max(
                    player_chat_threshold - player_chats,
                    0,
                ),
            }
        )

    qualifying_players = [
        item
        for item in player_chat_totals
        if item["qualifies"]
    ]

    non_qualifying_players = [
        item
        for item in player_chat_totals
        if not item["qualifies"]
    ]

    payable_chats = sum(
        item["chats"]
        for item in qualifying_players
    )

    # ---------------------------------------------------------
    # PREFERRED PAYROLL DAY
    # ---------------------------------------------------------

    payment_settings = PaymentSettings.objects.first()

    preferred_payment_day = (
        payment_settings.payment_day
        if payment_settings is not None
        else 3
    )

    days_until_preferred_payday = (
        preferred_payment_day - today.weekday()
    ) % 7

    next_payday = today + timedelta(
        days=days_until_preferred_payday,
    )

    # ---------------------------------------------------------
    # RECENT PAYMENTS
    # ---------------------------------------------------------

    payment_records = (
        PaymentRecord.objects
        .select_related(
            "moderator",
            "coverage_session",
            "coverage_session__player",
        )
        .order_by("-created_at")
    )

    recent_payments = list(
        payment_records
        .order_by("-created_at")[:10]
    )

    # ---------------------------------------------------------
    # CONTEXT
    # ---------------------------------------------------------

    context = {
        # General
        "today": today,
        "week_start": week_start,
        "next_payday": next_payday,
        "preferred_payment_day": preferred_payment_day,

        # Staff
        "total_staff": staff.count(),
        "active_staff": active_staff,
        "moderators_count": moderators.count(),
        "active_moderators": active_moderators,
        "managers_count": managers.count(),
        "active_managers": active_managers,

        # Players
        "total_players": total_players,
        "active_players": active_players,
        "inactive_players": inactive_players,

        # Coverage
        "total_coverage_sessions": total_coverage_sessions,
        "active_coverage_sessions": active_coverage_sessions,

        # Chats
        "total_chats": total_chats,
        "chats_this_week": chats_this_week,
        "chats_this_month": chats_this_month,

        # Player qualification
        "player_chat_totals": player_chat_totals,
        "qualifying_players": qualifying_players,
        "non_qualifying_players": non_qualifying_players,
        "qualifying_player_count": len(qualifying_players),
        "non_qualifying_player_count": len(
            non_qualifying_players
        ),
        "payable_chats": payable_chats,

        # Payments
        "total_payment_records": total_payment_records,
        "generated_amount": generated_amount,
        "paid_amount": paid_amount,
        "outstanding_amount": outstanding_amount,
        "unpaid_payment_records": unpaid_payment_records,
        "paid_payment_records": paid_payment_records,

        # Bonuses
        "total_bonuses": total_bonuses,
        "weekly_bonuses": weekly_bonuses,

        # Rates
        "current_rate_tier": current_rate_tier,
        "current_rate": current_rate,

        # Moderator performance
        "moderator_performance": moderator_performance,

        # Recent payments
        "recent_payments": recent_payments,

        # Completed End-of-Session Reports
        "completed_reports": list(
            completed_reports.order_by(
                "-operating_date",
                "-end_of_session_report__submitted_at",
            )[:20]
        ),
    }

    
    # --- Moderator Coverage Table Logic ---
    active_sessions = CoverageSession.objects.filter(status="ACTIVE").select_related("player", "moderator")
    
    # Map player_id to their active session
    covered_players = {s.player_id: s for s in active_sessions}
    
    all_players = Player.objects.filter(status="ACTIVE").order_by("player_number")
    
    coverage_rows = []
    for player in all_players:
        session = covered_players.get(player.id)
        if session:
            mod = session.moderator
            mod_name = mod.get_full_name() or mod.username
            status = "Covered"
            status_class = "bg-green-50 text-green-700 border-green-200"
            replacement_class = ""
            
            # Check for replacement request (assuming a field like `replacement_requested` exists, 
            # or checking the coverage alert)
            if getattr(session, "replacement_requested_at", None) is not None:
                replacement_class = '<span class="ml-2 inline-flex items-center px-2 py-0.5 rounded text-xs font-bold bg-amber-100 text-amber-800 border border-amber-300">Replacement Requested</span>'
        else:
            mod_name = "—"
            status = "Uncovered"
            status_class = "bg-red-50 text-red-700 border-red-200"
            replacement_class = ""

        coverage_rows.append({
            "player": str(player),
            "moderator": mod_name,
            "status": status,
            "status_class": status_class,
            "replacement_badge": replacement_class,
        })

    # Eligible moderators for the Force Replace dropdown on the director portal.
    # Excludes moderators currently covering a player or with a pending report.
    from coverage.models import CoverageSession as _CS
    _busy_mod_ids = set(
        _CS.objects.filter(
            status__in=(
                _CS.Status.ACTIVE,
                _CS.Status.OPEN,
                _CS.Status.AWAITING_REPORT,
                _CS.Status.HANDOVER,
                _CS.Status.REPLACEMENT_REQUESTED,
            )
        ).values_list("moderator_id", flat=True)
    )
    context["eligible_moderators"] = (
        User.objects.filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        )
        .exclude(id__in=_busy_mod_ids)
        .select_related("staff_profile")
        .order_by("first_name", "last_name", "username")
    )
    context["coverage_rows"] = coverage_rows
    # -------------------------------------

    return render(
        request,
        "dashboard/director_dashboard.html",
        context,
    )

@login_required(login_url="/login/")
def profile(request):
    profile_user = request.user
    staff_profile = getattr(profile_user, "staff_profile", None)

    if request.method == "POST":
        if staff_profile is None:
            messages.error(
                request,
                "Your staff profile is not available. Contact management for assistance.",
            )
            return redirect("dashboard:profile")

        form = StaffSelfProfileForm(
            request.POST,
            user=profile_user,
            staff_profile=staff_profile,
        )

        if form.is_valid():
            with transaction.atomic():
                profile_user.first_name = form.cleaned_data["first_name"].strip()
                profile_user.last_name = form.cleaned_data["last_name"].strip()

                new_email = form.cleaned_data["email"]
                profile_user.email = new_email
                profile_user.username = new_email

                profile_user.save(
                    update_fields=[
                        "first_name",
                        "last_name",
                        "email",
                        "username",
                    ]
                )

                staff_profile.phone_number = form.cleaned_data["phone_number"].strip()
                staff_profile.whatsapp_number = form.cleaned_data["whatsapp_number"].strip()
                staff_profile.mpesa_number = form.cleaned_data["mpesa_number"].strip()

                staff_profile.save(
                    update_fields=[
                        "phone_number",
                        "whatsapp_number",
                        "mpesa_number",
                        "updated_at",
                    ]
                )

            messages.success(
                request,
                "Your account details have been updated successfully.",
            )
            return redirect("dashboard:profile")
    else:
        form = StaffSelfProfileForm(
            user=profile_user,
            staff_profile=staff_profile,
        )

    return render(
        request,
        "dashboard/profile.html",
        {
            "profile_user": profile_user,
            "staff_profile": staff_profile,
            "form": form,
        },
    )

@login_required(login_url="/login/")
def password_change(request):
    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)

        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(
                request,
                "Your password has been changed successfully.",
            )
            return redirect("dashboard:password_change")
    else:
        form = PasswordChangeForm(request.user)

    return render(
        request,
        "dashboard/password_change.html",
        {"form": form},
    )
@role_required(*ADMIN_ROLES)
def admin_test(request):
    return render(
        request,
        "dashboard/admin_test.html",
    )

@login_required(login_url="/login/")
def coverage_history(request):
    if request.user.role != User.Role.MODERATOR:
        return render(
            request,
            "dashboard/coverage_history.html",
            {
                "coverage_sessions": [],
                "message": (
                    "Coverage History is available "
                    "to Moderators only."
                ),
            },
        )

    coverage_sessions = (
        CoverageSession.objects
        .select_related(
            "player",
            "replacement_moderator",
            "end_of_session_report",
        )
        .filter(
            moderator=request.user,
        )
        .order_by(
            "-operating_date",
            "-created_at",
        )
    )

    return render(
        request,
        "dashboard/coverage_history.html",
        {
            "coverage_sessions": coverage_sessions,
        },
    )

@login_required(login_url="/login/")
def my_shifts(request):
    """
    Redirect to dashboard. The My Shifts page has been replaced by the
    continuation popup on the dashboard, which handles YES/NO responses
    and redirects to the report form when appropriate.

    Kept as a redirect only so existing links/redirects to this URL
    still work without errors.
    """
    from django.shortcuts import redirect
    return redirect("dashboard:home")


