from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from .decorators import role_required
from .forms import (
    StaffCreationForm,
    StaffEditForm,
    StaffSuspensionForm,
)
from .models import StaffProfile, User
from .permissions import MANAGER_ROLES


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:
            if not user.is_active:
                messages.error(
                    request,
                    "Your account is inactive. Please contact the administrator.",
                )
                return render(
                    request,
                    "accounts/login.html",
                )

            login(request, user)

            return redirect("dashboard:home")

        messages.error(
            request,
            "Invalid username or password.",
        )

    return render(request, "accounts/login.html")


@login_required
def logout_view(request):
    logout(request)

    messages.success(
        request,
        "You have been logged out successfully.",
    )

    return redirect("accounts:login")


@role_required(*MANAGER_ROLES)
def staff_list(request):
    staff_profiles = (
        StaffProfile.objects
        .select_related("user")
        .all()
        .order_by(
            "user__first_name",
            "user__last_name",
        )
    )

    return render(
        request,
        "accounts/staff_list.html",
        {
            "staff_profiles": staff_profiles,
        },
    )


@role_required(*MANAGER_ROLES)
def staff_create(request):

    if request.method == "POST":
        form = StaffCreationForm(request.POST)

        if form.is_valid():

            with transaction.atomic():

                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                    email=form.cleaned_data["email"],
                    role=User.Role.MODERATOR,
                    is_active=True,
                )

                StaffProfile.objects.create(
                    user=user,
                    phone_number=form.cleaned_data["phone_number"],
                    status=StaffProfile.Status.ACTIVE,
                )

            messages.success(
                request,
                "Moderator account created successfully.",
            )

            return redirect("accounts:staff_list")

    else:
        form = StaffCreationForm()

    return render(
        request,
        "accounts/staff_create.html",
        {
            "form": form,
        },
    )


@role_required(*MANAGER_ROLES)
def staff_edit(request, staff_id):

    staff_profile = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_id,
    )

    user = staff_profile.user

    if request.method == "POST":
        form = StaffEditForm(
            request.POST,
            user=user,
            staff_profile=staff_profile,
        )

        if form.is_valid():

            with transaction.atomic():

                user.first_name = form.cleaned_data["first_name"]
                user.last_name = form.cleaned_data["last_name"]
                user.email = form.cleaned_data["email"]
                user.role = form.cleaned_data["role"]

                status = form.cleaned_data["status"]

                if status == StaffProfile.Status.ACTIVE:
                    user.is_active = True
                else:
                    user.is_active = False

                user.save()

                staff_profile.phone_number = (
                    form.cleaned_data["phone_number"]
                )
                staff_profile.status = status
                staff_profile.notes = form.cleaned_data["notes"]

                if status == StaffProfile.Status.SUSPENDED:
                    staff_profile.suspension_start = (
                        form.cleaned_data["suspension_start"]
                    )
                    staff_profile.suspension_end = (
                        form.cleaned_data["suspension_end"]
                    )
                    staff_profile.suspension_reason = (
                        form.cleaned_data["suspension_reason"]
                    )
                else:
                    staff_profile.suspension_start = None
                    staff_profile.suspension_end = None
                    staff_profile.suspension_reason = ""

                staff_profile.save()

            messages.success(
                request,
                f"{user.get_full_name() or user.username} was updated successfully.",
            )

            return redirect("accounts:staff_list")

    else:
        form = StaffEditForm(
            user=user,
            staff_profile=staff_profile,
        )

    return render(
        request,
        "accounts/staff_edit.html",
        {
            "form": form,
            "staff_profile": staff_profile,
            "staff_user": user,
        },
    )


@role_required(*MANAGER_ROLES)
def staff_activate(request, staff_id):

    if request.method != "POST":
        return redirect("accounts:staff_list")

    staff_profile = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_id,
    )

    user = staff_profile.user

    staff_profile.status = StaffProfile.Status.ACTIVE
    staff_profile.save()

    user.is_active = True
    user.save(update_fields=["is_active"])

    messages.success(
        request,
        f"{user.get_full_name() or user.username} has been activated.",
    )

    return redirect("accounts:staff_list")


@role_required(*MANAGER_ROLES)
def staff_suspend(request, staff_id):

    staff_profile = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_id,
    )

    user = staff_profile.user

    if request.method == "POST":

        form = StaffSuspensionForm(request.POST)

        if form.is_valid():

            staff_profile.status = StaffProfile.Status.SUSPENDED
            staff_profile.suspension_start = (
                form.cleaned_data["suspension_start"]
            )
            staff_profile.suspension_end = (
                form.cleaned_data["suspension_end"]
            )
            staff_profile.suspension_reason = (
                form.cleaned_data["suspension_reason"]
            )
            staff_profile.save()

            user.is_active = False
            user.save(update_fields=["is_active"])

            messages.warning(
                request,
                f"{user.get_full_name() or user.username} has been suspended "
                f"until {staff_profile.suspension_end:%d %B %Y at %H:%M}.",
            )

            return redirect("accounts:staff_list")

    else:
        form = StaffSuspensionForm()

    return render(
        request,
        "accounts/staff_suspend.html",
        {
            "form": form,
            "staff_profile": staff_profile,
            "staff_user": user,
        },
    )



@role_required(*MANAGER_ROLES)
def staff_terminate(request, staff_id):

    if request.method != "POST":
        return redirect("accounts:staff_list")

    staff_profile = get_object_or_404(
        StaffProfile.objects.select_related("user"),
        pk=staff_id,
    )

    user = staff_profile.user

    staff_profile.status = StaffProfile.Status.TERMINATED
    staff_profile.save()

    user.is_active = False
    user.save(update_fields=["is_active"])

    messages.error(
        request,
        f"{user.get_full_name() or user.username} has been terminated.",
    )

    return redirect("accounts:staff_list")





