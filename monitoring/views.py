from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.decorators import role_required
from accounts.models import StaffProfile
from accounts.permissions import CHAT_SUBMISSION_ROLES

from .forms import ChatSubmissionForm


@role_required(*CHAT_SUBMISSION_ROLES)
def submit_chat(request):

    staff_profile = getattr(
        request.user,
        "staff_profile",
        None,
    )

    if staff_profile is None:
        messages.error(
            request,
            "Your staff profile could not be found. Please contact management.",
        )
        return redirect("dashboard:home")

    if staff_profile.status in (
        StaffProfile.Status.SUSPENDED,
        StaffProfile.Status.TERMINATED,
    ):
        messages.error(
            request,
            "You cannot submit chats while your staff account is "
            f"{staff_profile.get_status_display().lower()}.",
        )
        return redirect("dashboard:home")

    if request.method == "POST":

        form = ChatSubmissionForm(request.POST)

        if form.is_valid():

            submission = form.save(commit=False)
            submission.moderator = request.user
            submission.save()

            messages.success(
                request,
                "Chat submission recorded successfully.",
            )

            return redirect("dashboard:home")

    else:
        form = ChatSubmissionForm()

    return render(
        request,
        "monitoring/submit_chat.html",
        {
            "form": form,
            "staff_profile": staff_profile,
        },
    )
