from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from accounts.models import User
from accounts.permissions import RATE_MANAGEMENT_ROLES

from .forms import PaymentSettingsForm
from .models import ModeratorPayment, PaymentRecord, PaymentSettings
from .services import build_payroll_plan, process_thursday_payroll
from .services import settle_moderator_payment


@role_required(*RATE_MANAGEMENT_ROLES)
def payroll_review(request):
    try:
        plan = build_payroll_plan(payment_date=date.today())
    except ValidationError as exc:
        messages.error(
            request,
            (
                f"Payroll cannot be computed: {exc} "
                "Please configure Player Chat Rate Tiers for all active "
                "players, then try again."
            ),
        )
        return redirect("dashboard:home")

    # Detect whether this week's payroll has already been processed so we
    # can show an accurate banner and prevent a confusing failed POST.
    already_processed = ModeratorPayment.objects.filter(
        payment_week_start=plan["week_start"],
        payment_week_end=plan["week_end"],
    ).exists()

    return render(
        request,
        "payments/payroll_review.html",
        {
            "plan": plan,
            "already_processed": already_processed,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def process_payroll(request):
    if request.method != "POST":
        return redirect("payments:payroll_review")

    try:
        result = process_thursday_payroll(payment_date=date.today())
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("payments:payroll_review")

    request.session["payroll_result"] = {
        "payment_date": result["payment_date"].isoformat(),
        "week_start": result["week_start"].isoformat(),
        "week_end": result["week_end"].isoformat(),
        "threshold": result["threshold"],
        "payments_created": result["payments_created"],
        "total_payable_chats": result["total_payable_chats"],
        "total_chat_earnings": str(result["total_chat_earnings"]),
        "total_bonuses": str(result["total_bonuses"]),
        "total_earned": str(result["total_earned"]),
    }
    return redirect("payments:payroll_results")


@role_required(User.Role.DIRECTOR)
def payroll_results(request):
    result = request.session.get("payroll_result")

    if not result:
        messages.info(
            request,
            "No recent payroll results are available.",
        )
        return redirect("payments:payroll_review")

    try:
        payment_date = date.fromisoformat(result["payment_date"])
        week_start = date.fromisoformat(result["week_start"])
        week_end = date.fromisoformat(result["week_end"])
    except (KeyError, TypeError, ValueError):
        request.session.pop("payroll_result", None)
        messages.error(
            request,
            "The stored payroll result could not be read.",
        )
        return redirect("payments:payroll_review")

    payments = list(
        ModeratorPayment.objects
        .filter(
            payment_week_start=week_start,
            payment_week_end=week_end,
        )
        .select_related("moderator")
        .order_by("moderator__username", "id")
    )

    return render(
        request,
        "payments/payroll_results.html",
        {
            "result": result,
            "payment_date": payment_date,
            "week_start": week_start,
            "week_end": week_end,
            "payments": payments,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def payment_settings(request):
    """
    Director-only page for managing the current Moderator payment
    configuration.
    """
    settings = PaymentSettings.objects.first()

    if request.method == "POST":
        form = PaymentSettingsForm(request.POST, instance=settings)

        if form.is_valid():
            form.save()
            messages.success(
                request,
                "Moderator payment settings updated successfully.",
            )
            if request.POST.get("action") == "review":
                return redirect("payments:payroll_review")
            return redirect("payments:payment_settings")
    else:
        form = PaymentSettingsForm(instance=settings)

    return render(
        request,
        "payments/payment_settings.html",
        {
            "form": form,
            "settings": settings,
        },
    )


@login_required(login_url="/login/")
def payment_history(request):
    if request.user.role != User.Role.MODERATOR:
        return render(
            request,
            "payments/payment_history.html",
            {
                "payment_records": [],
                "payroll_payments": [],
                "total_chats": 0,
                "unprocessed_chats": 0,
                "gross_earnings": Decimal("0.00"),
                "amount_paid": Decimal("0.00"),
                "outstanding_amount": Decimal("0.00"),
                "unpaid_count": 0,
                "paid_count": 0,
                "message": "Payment History is available to Moderators only.",
            },
        )

    payment_records = (
        PaymentRecord.objects
        .select_related(
            "coverage_session",
            "coverage_session__player",
        )
        .filter(
            moderator=request.user,
        )
        .order_by(
            "-created_at",
        )
    )

    payroll_payments = (
        ModeratorPayment.objects
        .filter(
            moderator=request.user,
        )
        .order_by(
            "-payment_week_end",
            "-id",
        )
    )

    for payment in payment_records:
        payment.unprocessed_chats = (
            payment.chats_responded - payment.payroll_processed_chats
        )

    total_chats = sum(
        payment.chats_responded
        for payment in payment_records
    )

    unprocessed_chats = sum(
        payment.chats_responded - payment.payroll_processed_chats
        for payment in payment_records
    )

    gross_earnings = sum(
        payment.earned_amount
        for payment in payroll_payments
    )

    amount_paid = sum(
        payment.amount_paid
        for payment in payroll_payments
    )

    outstanding_amount = sum(
        payment.outstanding_amount
        for payment in payroll_payments
    )

    unpaid_count = sum(
        1
        for payment in payroll_payments
        if payment.status == ModeratorPayment.Status.UNPAID
    )

    paid_count = sum(
        1
        for payment in payroll_payments
        if payment.status == ModeratorPayment.Status.PAID
    )

    return render(
        request,
        "payments/payment_history.html",
        {
            "payment_records": payment_records,
            "payroll_payments": payroll_payments,
            "total_chats": total_chats,
            "unprocessed_chats": unprocessed_chats,
            "gross_earnings": gross_earnings,
            "amount_paid": amount_paid,
            "outstanding_amount": outstanding_amount,
            "unpaid_count": unpaid_count,
            "paid_count": paid_count,
        },
    )


@login_required(login_url="/login/")
def settle_moderator_payment_view(request, payment_id):
    """
    Director-only endpoint for recording an actual payment against
    a generated ModeratorPayment payroll record.
    """
    if request.user.role != User.Role.DIRECTOR:
        messages.error(
            request,
            "Only Directors can settle Moderator payroll payments.",
        )
        return redirect("dashboard:home")

    moderator_payment = get_object_or_404(
        ModeratorPayment.objects.select_related("moderator"),
        id=payment_id,
    )

    if request.method != "POST":
        return render(
            request,
            "payments/settle_moderator_payment.html",
            {
                "moderator_payment": moderator_payment,
            },
        )

    raw_amount = request.POST.get("amount_paid", "").strip()
    payment_reference = request.POST.get("payment_reference", "").strip()
    notes = request.POST.get("notes", "").strip()

    if not raw_amount:
        messages.error(request, "Enter the payment amount.")
        return redirect(
            "payments:settle_moderator_payment",
            payment_id=moderator_payment.id,
        )

    try:
        amount_paid = Decimal(raw_amount)

        settle_moderator_payment(
            moderator_payment=moderator_payment,
            amount_paid=amount_paid,
            payment_reference=payment_reference,
            notes=notes,
        )

    except (ValidationError, ValueError, TypeError) as exc:
        messages.error(request, str(exc))
        return redirect(
            "payments:settle_moderator_payment",
            payment_id=moderator_payment.id,
        )

    messages.success(
        request,
        (
            f"Payment recorded successfully for "
            f"{moderator_payment.moderator.get_full_name() or moderator_payment.moderator.username}."
        ),
    )

    return redirect("dashboard:home")

@login_required(login_url="/login/")
def settle_payment(request, payment_id):
    """
    Reconciliation and settlement view for a single ModeratorPayment.

    Shows the source sessions, per-player breakdown, and carried-forward
    chats. On POST, records the payment (M-Pesa reference + amount).
    """
    from django.db.models import F, Sum
    from payments.models import ModeratorPayment, PaymentRecord, PaymentSettings

    payment = get_object_or_404(ModeratorPayment, pk=payment_id)

    role = getattr(request.user, "role", None)
    is_director = role in ("DIRECTOR", "ADMIN", "MANAGER")
    is_owner = payment.moderator_id == request.user.id

    if not (is_director or is_owner):
        messages.error(request, "You do not have permission to view this payment.")
        return redirect("dashboard:home")

    if request.method == "POST":
        if not is_director:
            messages.error(request, "Only Directors can record payments.")
            return redirect("payments:settle_payment", payment_id=payment.id)
        from .services import record_payment
        try:
            record_payment(
                payment=payment,
                director=request.user,
                mpesa_reference=request.POST.get("mpesa_reference", ""),
                amount=request.POST.get("amount", "0"),
            )
            messages.success(
                request,
                f"Payment of KES {payment.amount_paid} recorded for "
                f"{payment.moderator.get_full_name() or payment.moderator.username}.",
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Unexpected error: {exc}")
        return redirect("payments:settle_payment", payment_id=payment.id)

    # Source PaymentRecord rows consumed by THIS ModeratorPayment.
    # Only records with consumed_by=payment are shown. Historical payments
    # created before the FK existed have consumed_by=NULL — for those we
    # show an honest "unavailable" state rather than guessing.
    source_records = (
        PaymentRecord.objects
        .filter(consumed_by=payment)
        .select_related(
            "coverage_session",
            "coverage_session__player",
            "coverage_session__moderator",
        )
        .order_by("coverage_session__operating_date", "coverage_session__id")
    )

    historical_fallback = not source_records.exists() and payment.payable_chats > 0

    # Report submitted_at per session, if any
    from coverage.models import EndOfSessionReport
    session_ids = [r.coverage_session_id for r in source_records]
    submitted_map = dict(
        EndOfSessionReport.objects
        .filter(coverage_session_id__in=session_ids)
        .values_list("coverage_session_id", "submitted_at")
    )

    # Per-player breakdown — use stored JSON if available
    breakdown = payment.player_chat_rate_breakdown or {}

    # Distinct players this moderator was paid for in this week
    player_ids = list({
        r.coverage_session.player_id for r in source_records
    })

    # Carried-forward info per player
    threshold = (
        PaymentSettings.objects.first().minimum_chats_per_player
        if PaymentSettings.objects.exists() else 700
    )
    carried = {}
    for pid in player_ids:
        # Accumulated unpaid chats (across all weeks) for this player
        agg = (
            PaymentRecord.objects
            .filter(
                coverage_session__player_id=pid,
                chats_responded__gt=F("payroll_processed_chats"),
            )
            .aggregate(total=Sum(F("chats_responded") - F("payroll_processed_chats")))
        )
        accumulated_unpaid = agg["total"] or 0

        # Submitted this week for this player (regardless of moderator)
        week_agg = (
            PaymentRecord.objects
            .filter(
                coverage_session__player_id=pid,
                coverage_session__operating_date__gte=payment.payment_week_start,
                coverage_session__operating_date__lte=payment.payment_week_end,
            )
            .aggregate(total=Sum("chats_responded"))
        )
        submitted_this_week = week_agg["total"] or 0

        carried[pid] = {
            "submitted_this_week": submitted_this_week,
            "accumulated_unpaid": accumulated_unpaid,
            "threshold": threshold,
            "remaining_to_qualify": max(0, threshold - accumulated_unpaid),
        }

    # Resolve player objects for display
    from players.models import Player
    players = {
        p.id: p for p in Player.objects.filter(id__in=player_ids)
    }

    rows = []
    for r in source_records:
        session = r.coverage_session
        rows.append({
            "session_id": session.id,
            "session_code": getattr(session, "session_code", "") or "",
            "player": session.player,
            "operating_date": session.operating_date,
            "session_type": session.get_session_type_display(),
            "submitted_at": submitted_map.get(session.id),
            "chats_responded": r.chats_responded,
            "payroll_processed_chats": r.payroll_processed_chats,
        })

    # Pre-resolve player labels for the template
    player_labels = {pid: str(p) for pid, p in players.items()}

    # Enrich breakdown and carried with the resolved player label
    breakdown_display = [
        {
            "player_id": pid,
            "player_label": player_labels.get(int(pid), f"Player #{pid}"),
            "qualifying_chats": info.get("qualifying_chats", 0),
            "rate_per_chat": info.get("rate_per_chat", "0.00"),
            "chat_earnings": info.get("chat_earnings", "0.00"),
        }
        for pid, info in (breakdown or {}).items()
    ]

    carried_display = [
        {
            "player_id": pid,
            "player_label": player_labels.get(pid, f"Player #{pid}"),
            "submitted_this_week": info["submitted_this_week"],
            "accumulated_unpaid": info["accumulated_unpaid"],
            "threshold": info["threshold"],
            "remaining_to_qualify": info["remaining_to_qualify"],
        }
        for pid, info in carried.items()
    ]

    moderator_profile = getattr(payment.moderator, "staff_profile", None)
    moderator_mpesa = (moderator_profile.mpesa_number or "").strip() if moderator_profile else ""
    mpesa_missing = not moderator_mpesa

    context = {
        "payment": payment,
        "rows": rows,
        "breakdown_display": breakdown_display,
        "carried_display": carried_display,
        "threshold": threshold,
        "is_director": is_director,
        "mpesa_missing": mpesa_missing,
    }
    return render(request, "payments/settle_payment.html", context)

@login_required(login_url="/login/")
def my_payments(request):
    """List all payments for the logged-in moderator."""
    if getattr(request.user, "role", None) != "MODERATOR":
        messages.error(request, "This page is for moderators only.")
        return redirect("dashboard:home")

    payments = (
        ModeratorPayment.objects
        .filter(moderator=request.user)
        .order_by("-payment_week_start", "-id")
    )

    totals = {
        "earned": sum((p.earned_amount or 0) for p in payments),
        "paid": sum((p.amount_paid or 0) for p in payments),
        "outstanding": sum((p.outstanding_amount or 0) for p in payments),
    }

    return render(
        request,
        "payments/my_payments.html",
        {
            "payments": payments,
            "totals": totals,
        },
    )

@login_required(login_url="/login/")
def download_payment_statement_pdf(request, payment_id):
    """Generate and return a PDF payment statement for a ModeratorPayment."""
    from django.http import HttpResponse
    from django.db.models import F, Sum
    from payments.models import ModeratorPayment, PaymentRecord, PaymentSettings
    from payments.pdf import build_payment_statement_pdf

    payment = get_object_or_404(ModeratorPayment, pk=payment_id)

    role = getattr(request.user, "role", None)
    is_director = role in ("DIRECTOR", "ADMIN", "MANAGER")
    is_owner = payment.moderator_id == request.user.id

    if not (is_director or is_owner):
        messages.error(request, "You do not have permission to download this statement.")
        return redirect("dashboard:home")

    # Gather the same context the settle view uses
    source_records = (
        PaymentRecord.objects
        .filter(consumed_by=payment)
        .select_related("coverage_session", "coverage_session__player")
        .order_by("coverage_session__operating_date", "coverage_session__id")
    )
    if not source_records.exists():
        source_records = (
            PaymentRecord.objects
            .filter(moderator=payment.moderator, payroll_processed_chats__gt=0)
            .select_related("coverage_session", "coverage_session__player")
            .order_by("coverage_session__operating_date", "coverage_session__id")
        )

    from coverage.models import EndOfSessionReport
    session_ids = [r.coverage_session_id for r in source_records]
    submitted_map = dict(
        EndOfSessionReport.objects
        .filter(coverage_session_id__in=session_ids)
        .values_list("coverage_session_id", "submitted_at")
    )

    rows = []
    for r in source_records:
        session = r.coverage_session
        rows.append({
            "session_id": session.id,
            "session_code": getattr(session, "session_code", "") or "",
            "player": session.player,
            "operating_date": session.operating_date,
            "session_type": session.get_session_type_display(),
            "submitted_at": submitted_map.get(session.id),
            "chats_responded": r.chats_responded,
            "payroll_processed_chats": r.payroll_processed_chats,
        })

    breakdown = payment.player_chat_rate_breakdown or {}
    from players.models import Player
    player_ids = list({r.coverage_session.player_id for r in source_records})
    players = {p.id: p for p in Player.objects.filter(id__in=player_ids)}
    breakdown_display = [
        {
            "player_label": str(players.get(int(pid), f"Player #{pid}")),
            "qualifying_chats": info.get("qualifying_chats", 0),
            "rate_per_chat": info.get("rate_per_chat", "0.00"),
            "chat_earnings": info.get("chat_earnings", "0.00"),
        }
        for pid, info in breakdown.items()
    ]

    threshold = (
        PaymentSettings.objects.first().minimum_chats_per_player
        if PaymentSettings.objects.exists() else 700
    )
    carried_display = []
    for pid in player_ids:
        agg = (
            PaymentRecord.objects
            .filter(
                coverage_session__player_id=pid,
                chats_responded__gt=F("payroll_processed_chats"),
            )
            .aggregate(total=Sum(F("chats_responded") - F("payroll_processed_chats")))
        )
        week_agg = (
            PaymentRecord.objects
            .filter(
                coverage_session__player_id=pid,
                coverage_session__operating_date__gte=payment.payment_week_start,
                coverage_session__operating_date__lte=payment.payment_week_end,
            )
            .aggregate(total=Sum("chats_responded"))
        )
        accumulated = agg["total"] or 0
        carried_display.append({
            "player_label": str(players.get(pid, f"Player #{pid}")),
            "submitted_this_week": week_agg["total"] or 0,
            "accumulated_unpaid": accumulated,
            "threshold": threshold,
            "remaining_to_qualify": max(0, threshold - accumulated),
        })

    buffer = build_payment_statement_pdf(payment, rows, breakdown_display, carried_display)

    filename = f"payment-statement-{payment.id}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

@role_required(*RATE_MANAGEMENT_ROLES)
def export_payments_csv(request):
    """Export all ModeratorPayment rows as a CSV file for Directors."""
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="moderator-payments.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Payment ID", "Moderator", "M-Pesa Number",
        "Period Start", "Period End", "Payable Chats",
        "Chat Earnings (KES)", "Bonus (KES)", "Total Earned (KES)",
        "Amount Paid (KES)", "Outstanding (KES)",
        "Status", "M-Pesa Reference", "Paid At", "Paid By",
    ])

    payments = (
        ModeratorPayment.objects
        .select_related("moderator", "paid_by", "moderator__staff_profile")
        .order_by("-payment_week_start", "-id")
    )

    for p in payments:
        mpesa_number = ""
        sp = getattr(p.moderator, "staff_profile", None)
        if sp:
            mpesa_number = sp.mpesa_number or ""
        writer.writerow([
            p.id,
            p.moderator.get_full_name() or p.moderator.username,
            mpesa_number,
            p.payment_week_start.isoformat(),
            p.payment_week_end.isoformat(),
            p.payable_chats,
            p.chat_earnings,
            p.bonus_earned,
            p.earned_amount,
            p.amount_paid or "0.00",
            p.outstanding_amount or "0.00",
            p.get_status_display(),
            p.mpesa_reference or "",
            p.paid_at.isoformat() if p.paid_at else "",
            (p.paid_by.get_full_name() or p.paid_by.username) if p.paid_by else "",
        ])

    return response

@role_required(*RATE_MANAGEMENT_ROLES)
def payment_console(request):
    """
    Director payment console — grouped by moderator.

    Shows one row per moderator with aggregate outstanding amounts
    across all unpaid weeks. Clicking "Pay All" opens a per-moderator
    settlement page (Commit B).
    """
    from django.db.models import Count, Sum
    from accounts.models import User

    tab = request.GET.get("tab", "unpaid")
    if tab not in ("unpaid", "paid", "all"):
        tab = "unpaid"

    # Optional: filter to a single moderator via ?moderator=<id>
    filter_moderator_id = request.GET.get("moderator")
    filter_moderator = None
    if filter_moderator_id:
        try:
            from accounts.models import User as _User
            filter_moderator = _User.objects.filter(pk=int(filter_moderator_id), role=_User.Role.MODERATOR).first()
        except (ValueError, TypeError):
            filter_moderator = None

    base_qs = ModeratorPayment.objects.select_related("moderator")
    if filter_moderator:
        base_qs = base_qs.filter(moderator=filter_moderator)

    if tab == "unpaid":
        base_qs = base_qs.exclude(status=ModeratorPayment.Status.PAID)
    elif tab == "paid":
        base_qs = base_qs.filter(status=ModeratorPayment.Status.PAID)
    # tab == "all" → no filter

    # Group by moderator
    grouped = (
        base_qs
        .values("moderator_id")
        .annotate(
            record_count=Count("id"),
            total_payable_chats=Sum("payable_chats"),
            total_earned=Sum("earned_amount"),
            total_paid=Sum("amount_paid"),
            total_outstanding=Sum("outstanding_amount"),
        )
        .order_by("-total_outstanding", "moderator_id")
    )

    # Resolve moderator objects and M-Pesa info for each row
    moderator_ids = [g["moderator_id"] for g in grouped]
    # Note: staff_profile is a reverse OneToOne, so it cannot be select_related.
    # prefetch_related works for reverse relations but for ~10 moderators the
    # N+1 is negligible — just fetch and access inline.
    moderators = {
        u.id: u for u in User.objects.filter(id__in=moderator_ids)
    }

    rows = []
    for g in grouped:
        mod = moderators.get(g["moderator_id"])
        if not mod:
            continue
        profile = getattr(mod, "staff_profile", None)
        mpesa = (profile.mpesa_number or "").strip() if profile else ""
        rows.append({
            "moderator_id": g["moderator_id"],
            "moderator": mod,
            "record_count": g["record_count"],
            "total_payable_chats": g["total_payable_chats"] or 0,
            "total_earned": g["total_earned"] or 0,
            "total_paid": g["total_paid"] or 0,
            "total_outstanding": g["total_outstanding"] or 0,
            "mpesa_present": bool(mpesa),
            "mpesa_number": mpesa,
        })

    # Summary totals across ALL records (not just the current tab)
    all_qs = ModeratorPayment.objects.all()
    summary = all_qs.aggregate(
        total_earned=Sum("earned_amount"),
        total_paid=Sum("amount_paid"),
        total_outstanding=Sum("outstanding_amount"),
    )
    summary_counts = {
        "total": all_qs.count(),
        "unpaid": all_qs.exclude(status=ModeratorPayment.Status.PAID).count(),
        "paid": all_qs.filter(status=ModeratorPayment.Status.PAID).count(),
    }

    from decimal import Decimal
    total_count = summary_counts["total"] or 0
    total_earned = summary.get("total_earned") or Decimal("0.00")
    summary["avg"] = (total_earned / total_count) if total_count else Decimal("0.00")

    return render(
        request,
        "payments/payment_console.html",
        {
            "rows": rows,
            "tab": tab,
            "summary": summary,
            "summary_counts": summary_counts,
        },
    )
@role_required(*RATE_MANAGEMENT_ROLES)
def request_mpesa_notification(request, moderator_id):
    """
    Send the selected moderator a notification asking them to add their
    M-Pesa number so payment can be processed. Idempotent — safe to call
    repeatedly; each call creates one notification.
    """
    from accounts.models import User
    from notifications.models import Notification

    if request.method != "POST":
        return redirect("payments:payment_console")

    moderator = get_object_or_404(User, pk=moderator_id, role=User.Role.MODERATOR)

    profile = getattr(moderator, "staff_profile", None)
    current_mpesa = (profile.mpesa_number or "").strip() if profile else ""

    if current_mpesa:
        messages.info(
            request,
            f"{moderator.get_full_name() or moderator.username} already has an M-Pesa number on file.",
        )
        return redirect("payments:payment_console")

    # Compute the outstanding balance for a helpful message
    from django.db.models import Sum
    outstanding = (
        ModeratorPayment.objects
        .filter(moderator=moderator)
        .aggregate(total=Sum("outstanding_amount"))
        ["total"] or 0
    )

    Notification.objects.create(
        recipient=moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.CRITICAL,
        title="M-Pesa Number Required",
        message=(
            "Management has requested your M-Pesa number so your payment can "
            f"be processed. Outstanding balance: KES {outstanding}. "
            "Please add your personal M-Pesa number in your profile "
            "(/dashboard/profile/) as soon as possible."
        ),
    )

    messages.success(
        request,
        f"Notification sent to {moderator.get_full_name() or moderator.username}.",
    )
    return redirect("payments:payment_console")

@role_required(*RATE_MANAGEMENT_ROLES)
def set_moderator_mpesa(request, moderator_id):
    """
    Director sets a moderator's M-Pesa number with a required reason.
    Logs the change and sends a CRITICAL notification to the moderator.
    """
    from accounts.models import User, MpesaResetLog
    from notifications.models import Notification
    import re

    if request.method != "POST":
        return redirect("payments:payment_console")

    moderator = get_object_or_404(User, pk=moderator_id, role=User.Role.MODERATOR)

    raw_number = request.POST.get("mpesa_number", "").strip()
    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(request, "A reason is required when setting an M-Pesa number.")
        return redirect("payments:payment_console")

    # Normalize
    normalized = re.sub(r"[\s-]+", "", raw_number)
    if normalized.startswith("+254"):
        normalized = normalized[1:]
    if re.fullmatch(r"0[17]\d{8}", normalized):
        pass
    elif re.fullmatch(r"254[17]\d{8}", normalized):
        pass
    else:
        messages.error(
            request,
            "Enter a valid Kenyan M-Pesa number (e.g. 0712345678 or 254712345678).",
        )
        return redirect("payments:payment_console")

    profile = getattr(moderator, "staff_profile", None)
    if profile is None:
        messages.error(request, f"{moderator.username} has no staff profile.")
        return redirect("payments:payment_console")

    # Uniqueness: ensure no other moderator has this number
    from accounts.models import StaffProfile
    conflict = StaffProfile.objects.filter(mpesa_number=normalized).exclude(pk=profile.pk).first()
    if conflict:
        messages.error(
            request,
            f"This M-Pesa number is already registered to another moderator "
            f"({conflict.user.username}).",
        )
        return redirect("payments:payment_console")

    previous = profile.mpesa_number or ""
    profile.mpesa_number = normalized
    profile.save(update_fields=["mpesa_number", "updated_at"])

    MpesaResetLog.objects.create(
        moderator=moderator,
        reset_by=request.user,
        previous_number=previous,
        new_number=normalized,
        change_type="SET",
        reason=reason,
    )

    moderator_label = moderator.get_full_name() or moderator.username
    actor_label = request.user.get_full_name() or request.user.username

    Notification.objects.create(
        recipient=moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.CRITICAL,
        title="M-Pesa Number Set by Management",
        message=(
            f"Your M-Pesa number was set to {normalized} by {actor_label} "
            f"({request.user.role}). Reason: {reason}. "
            "If this is incorrect, please update your profile immediately "
            "(/dashboard/profile/)."
        ),
    )

    messages.success(
        request,
        f"M-Pesa set for {moderator_label}. Notification sent.",
    )
    return redirect("payments:payment_console")


@role_required(*RATE_MANAGEMENT_ROLES)
def reset_moderator_mpesa(request, moderator_id):
    """
    Director clears a moderator's M-Pesa number with a required reason.
    Logs the change and sends a CRITICAL notification to the moderator.
    """
    from accounts.models import User, MpesaResetLog
    from notifications.models import Notification

    if request.method != "POST":
        return redirect("payments:payment_console")

    moderator = get_object_or_404(User, pk=moderator_id, role=User.Role.MODERATOR)
    reason = request.POST.get("reason", "").strip()

    if not reason:
        messages.error(request, "A reason is required when resetting an M-Pesa number.")
        return redirect("payments:payment_console")

    profile = getattr(moderator, "staff_profile", None)
    if profile is None:
        messages.error(request, f"{moderator.username} has no staff profile.")
        return redirect("payments:payment_console")

    previous = profile.mpesa_number or ""
    if not previous:
        messages.info(
            request,
            f"{moderator.get_full_name() or moderator.username} has no M-Pesa number to reset.",
        )
        return redirect("payments:payment_console")

    profile.mpesa_number = ""
    profile.save(update_fields=["mpesa_number", "updated_at"])

    MpesaResetLog.objects.create(
        moderator=moderator,
        reset_by=request.user,
        previous_number=previous,
        new_number="",
        change_type="RESET",
        reason=reason,
    )

    moderator_label = moderator.get_full_name() or moderator.username
    actor_label = request.user.get_full_name() or request.user.username

    Notification.objects.create(
        recipient=moderator,
        notification_type=Notification.NotificationType.GENERAL,
        alert_level=Notification.AlertLevel.CRITICAL,
        title="M-Pesa Number Reset",
        message=(
            f"Your M-Pesa number ({previous}) was reset by {actor_label}. "
            f"Reason: {reason}. Please enter your correct M-Pesa number in "
            "your profile (/dashboard/profile/) so payments can be processed."
        ),
    )

    messages.success(
        request,
        f"M-Pesa reset for {moderator_label}. Notification sent.",
    )
    return redirect("payments:payment_console")

@role_required(*RATE_MANAGEMENT_ROLES)
def settle_moderator_payments(request, moderator_id):
    """
    Per-moderator settlement: shows all unpaid records and a single form
    that records one M-Pesa transaction covering them sequentially.
    """
    from accounts.models import User
    from decimal import Decimal

    moderator = get_object_or_404(User, pk=moderator_id, role=User.Role.MODERATOR)
    profile = getattr(moderator, "staff_profile", None)
    mpesa = (profile.mpesa_number or "").strip() if profile else ""

    unpaid = (
        ModeratorPayment.objects
        .filter(moderator=moderator)
        .exclude(status=ModeratorPayment.Status.PAID)
        .order_by("payment_week_start", "id")
    )
    unpaid_list = list(unpaid)
    total_outstanding = sum(
        (mp.outstanding_amount or Decimal("0.00")) for mp in unpaid_list
    )

    if request.method == "POST":
        from .services import record_payment_group
        try:
            record_payment_group(
                moderator=moderator,
                director=request.user,
                mpesa_reference=request.POST.get("mpesa_reference", ""),
                amount=request.POST.get("amount", "0"),
            )
            messages.success(
                request,
                f"Payment recorded for {moderator.get_full_name() or moderator.username}.",
            )
        except ValidationError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Unexpected error: {exc}")
        return redirect("payments:settle_moderator_payments", moderator_id=moderator.id)

    return render(
        request,
        "payments/settle_moderator_payments.html",
        {
            "moderator": moderator,
            "mpesa_number": mpesa,
            "unpaid_records": unpaid_list,
            "total_outstanding": total_outstanding,
        },
    )
