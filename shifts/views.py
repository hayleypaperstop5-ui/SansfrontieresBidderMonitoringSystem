from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from accounts.permissions import MANAGER_ROLES, CHAT_SUBMISSION_ROLES

from .forms import ShiftCreationForm, ReplacementModeratorAssignmentForm
from .models import Shift
from .services import has_outstanding_shift_report


@role_required(*MANAGER_ROLES)
def shift_list(request):
    shifts = Shift.objects.select_related(
        "player",
        "primary_moderator",
        "substitute",
    ).all()

    return render(
        request,
        "shifts/shift_list.html",
        {
            "shifts": shifts,
        },
    )


@role_required(*MANAGER_ROLES)
def shift_create(request):
    if request.method == "POST":
        form = ShiftCreationForm(request.POST)

        if form.is_valid():
            moderator = form.cleaned_data["primary_moderator"]

            if has_outstanding_shift_report(moderator):
                form.add_error(
                    "primary_moderator",
                    "This Moderator cannot be assigned a new shift because an outstanding shift report is required.",
                )
            else:
                shift = form.save()

                messages.success(
                    request,
                    f"Shift for Player {shift.player.player_number} "
                    f"on {shift.date:%d %b %Y} created successfully.",
                )

                return redirect("shifts:shift_list")

    else:
        form = ShiftCreationForm()

    return render(
        request,
        "shifts/shift_create.html",
        {
            "form": form,
        },
    )


@role_required(*MANAGER_ROLES)
def shift_assign_substitute(request, shift_id):
    from datetime import datetime
    from django.utils import timezone

    shift = get_object_or_404(
        Shift.objects.select_related(
            "player",
            "primary_moderator",
            "substitute",
        ),
        pk=shift_id,
    )

    scheduled_start = timezone.make_aware(
        datetime.combine(
            shift.date,
            shift.scheduled_start,
        ),
        timezone.get_current_timezone(),
    )

    if shift.status != Shift.Status.SCHEDULED:
        messages.error(
            request,
            "Replacement Moderator cannot be assigned or changed because this shift is no longer Scheduled.",
        )
        return redirect("shifts:shift_list")

    if timezone.now() >= scheduled_start:
        messages.error(
            request,
            "Replacement Moderator cannot be assigned or changed after the scheduled shift start time.",
        )
        return redirect("shifts:shift_list")

    if request.method == "POST":
        form = ReplacementModeratorAssignmentForm(
            request.POST,
            instance=shift,
        )

        if form.is_valid():
            replacement_moderator = form.cleaned_data["substitute"]

            if has_outstanding_shift_report(replacement_moderator):
                form.add_error(
                    "substitute",
                    "This Moderator cannot be assigned as a replacement because an outstanding shift report is required.",
                )
            elif replacement_moderator == shift.primary_moderator:
                form.add_error(
                    "substitute",
                    "The Primary Moderator cannot also be assigned as the Replacement Moderator.",
                )
            else:
                shift = form.save()

                messages.success(
                    request,
                    f"Replacement Moderator assigned to Player {shift.player.player_number} "
                    f"shift on {shift.date:%d %b %Y} successfully.",
                )

                return redirect("shifts:shift_list")

    else:
        form = ReplacementModeratorAssignmentForm(instance=shift)

    return render(
        request,
        "shifts/shift_assign_substitute.html",
        {
            "form": form,
            "shift": shift,
        },
    )


@role_required(*CHAT_SUBMISSION_ROLES)
def shift_sign_in(request, shift_id):
    from django.utils import timezone

    shift = get_object_or_404(
        Shift.objects.select_related(
            "player",
            "primary_moderator",
            "substitute",
        ),
        pk=shift_id,
    )

    if request.user not in (
        shift.primary_moderator,
        shift.substitute,
    ):
        messages.error(
            request,
            "You are not assigned to this shift.",
        )
        return redirect("dashboard:home")

    if shift.actual_sign_in:
        messages.info(
            request,
            "This shift has already been signed in.",
        )
        return redirect("dashboard:home")

    if has_outstanding_shift_report(request.user):
        messages.error(
            request,
            "You cannot start this shift because you have an outstanding shift report.",
        )
        return redirect("dashboard:home")

    shift.actual_worker = request.user
    shift.actual_sign_in = timezone.now()
    shift.status = Shift.Status.IN_PROGRESS
    shift.save(
        update_fields=[
            "actual_worker",
            "actual_sign_in",
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        f"You have successfully signed in for the Player "
        f"{shift.player.player_number} shift.",
    )

    return redirect("dashboard:my_shifts")


@role_required(*CHAT_SUBMISSION_ROLES)
def shift_sign_out(request, shift_id):
    from django.utils import timezone

    shift = get_object_or_404(
        Shift.objects.select_related(
            "player",
            "primary_moderator",
            "substitute",
            "actual_worker",
        ),
        pk=shift_id,
    )

    if shift.actual_worker != request.user:
        messages.error(
            request,
            "Only the worker who signed in for this shift can sign out.",
        )
        return redirect("dashboard:home")

    if not shift.actual_sign_in:
        messages.error(
            request,
            "You must sign in before you can sign out.",
        )
        return redirect("dashboard:home")

    if shift.actual_sign_out:
        messages.info(
            request,
            "This shift has already been signed out.",
        )
        return redirect("dashboard:home")

    shift.actual_sign_out = timezone.now()
    shift.status = Shift.Status.AWAITING_REPORT
    shift.save(
        update_fields=[
            "actual_sign_out",
            "status",
            "updated_at",
        ]
    )

    messages.success(
        request,
        "You have successfully signed out. Please submit your End-of-Shift Report.",
    )

    return redirect(
        "reports:shift_report_submit",
        shift_id=shift.id,
    )

