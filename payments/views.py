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
    plan = build_payroll_plan(payment_date=date.today())
    return render(request, "payments/payroll_review.html", {"plan": plan})


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