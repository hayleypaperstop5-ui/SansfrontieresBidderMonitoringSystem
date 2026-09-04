from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import User
from shifts.models import Shift

from .forms import ShiftReportForm
from .models import ShiftReport


@login_required(login_url="/login/")
def shift_report_submit(request, shift_id):
    shift = get_object_or_404(
        Shift.objects.select_related(
            "player",
            "primary_moderator",
            "substitute",
            "actual_worker",
        ),
        pk=shift_id,
    )

    if request.user.role != User.Role.MODERATOR:
        messages.error(
            request,
            "Only Moderators can submit shift reports.",
        )
        return redirect("dashboard:home")

    if shift.actual_worker != request.user:
        messages.error(
            request,
            "Only the Moderator who actually worked this shift can submit the report.",
        )
        return redirect("dashboard:home")

    if not shift.actual_sign_in:
        messages.error(
            request,
            "You must sign in to the shift before submitting a report.",
        )
        return redirect("dashboard:home")

    if not shift.actual_sign_out:
        messages.error(
            request,
            "You must sign out of the shift before submitting the report.",
        )
        return redirect("dashboard:home")

    if hasattr(shift, "report"):
        messages.info(
            request,
            "A report has already been submitted for this shift.",
        )
        return redirect("dashboard:home")

    if request.method == "POST":
        form = ShiftReportForm(request.POST, request.FILES)

        if form.is_valid():
            report = form.save(commit=False)
            report.shift = shift
            report.worker = request.user
            report.player = shift.player
            report.save()

            shift.status = Shift.Status.COMPLETED
            shift.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            messages.success(
                request,
                "Your end-of-shift report has been submitted successfully.",
            )

            return redirect("dashboard:my_shifts")

    else:
        form = ShiftReportForm()

    return render(
        request,
        "reports/shift_report_submit.html",
        {
            "form": form,
            "shift": shift,
        },
    )

