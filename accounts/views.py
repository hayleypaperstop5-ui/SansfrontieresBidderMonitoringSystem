from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.conf import settings
from datetime import timedelta
import hashlib
import secrets
import uuid
from accounts.utils import normalize_whatsapp_number

from .decorators import role_required
from .forms import (
    StaffCreationForm,
    StaffInvitationForm,
    ModeratorSetupForm,
    StaffEditForm,
    StaffSuspensionForm,
)
from .models import StaffInvitation, StaffProfile, StaffRole, User
from .permissions import MANAGER_ROLES, DIRECTOR_ROLES

def _activate_expired_suspensions():
    now = timezone.now()

    expired_suspensions = (
        StaffProfile.objects
        .select_related("user")
        .filter(
            status=StaffProfile.Status.SUSPENDED,
            suspension_end__isnull=False,
            suspension_end__lte=now,
        )
    )

    for staff_profile in expired_suspensions:
        staff_profile.status = StaffProfile.Status.ACTIVE
        staff_profile.suspension_start = None
        staff_profile.suspension_end = None
        staff_profile.suspension_reason = ""
        staff_profile.save(
            update_fields=[
                "status",
                "suspension_start",
                "suspension_end",
                "suspension_reason",
                "updated_at",
            ]
        )

        if not staff_profile.user.is_active:
            staff_profile.user.is_active = True
            staff_profile.user.save(update_fields=["is_active"])


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")

    if request.method == "POST":
        _activate_expired_suspensions()

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

    return render(
        request,
        "accounts/login.html",
    )


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
    _activate_expired_suspensions()

    if request.user.role in DIRECTOR_ROLES:
        active_invitation = StaffInvitation.objects.filter(
            user=OuterRef("user"),
            used_at__isnull=True,
            revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        )

        staff_members = (
            StaffProfile.objects
            .select_related("user", "designation")
            .annotate(has_active_invitation=Exists(active_invitation))
            .all()
            .order_by("user__first_name", "user__last_name", "user__username")
        )

        total_staff = staff_members.count()
        active_staff = staff_members.filter(
            status=StaffProfile.Status.ACTIVE
        ).count()
        moderator_count = staff_members.filter(
            user__role=User.Role.MODERATOR
        ).count()
        manager_count = staff_members.filter(
            user__role=User.Role.MANAGER
        ).count()

        return render(
            request,
            "accounts/director_staff_list.html",
            {
                "staff_members": staff_members,
                "staff": staff_members,
                "total_staff": total_staff,
                "active_staff": active_staff,
                "moderator_count": moderator_count,
                "manager_count": manager_count,
            },
        )

    moderators = (
        StaffProfile.objects
        .select_related("user", "designation")
        .filter(user__role=User.Role.MODERATOR)
        .order_by("user__first_name", "user__last_name")
    )

    active_moderators = moderators.filter(
        status=StaffProfile.Status.ACTIVE
    ).count()

    for moderator in moderators:
        moderator.whatsapp_number = normalize_whatsapp_number(
            moderator.phone_number
        )

    return render(
        request,
        "accounts/staff_list.html",
        {
            "moderators": moderators,
            "staff_profiles": moderators,
            "active_moderators": active_moderators,
            "whatsapp_contact_number": settings.WHATSAPP_CONTACT_NUMBER,
        },
    )

@role_required(*MANAGER_ROLES)
def staff_create(request):
    if request.method == "POST":
        form = StaffInvitationForm(request.POST)

        if form.is_valid():
            first_name = form.cleaned_data["first_name"].strip()
            last_name = form.cleaned_data["last_name"].strip()
            email = form.cleaned_data["email"]

            raw_token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
            temporary_username = f"pending_{uuid.uuid4().hex}"

            with transaction.atomic():
                user = User.objects.create(
                    username=temporary_username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    role=User.Role.MODERATOR,
                    is_active=False,
                )
                user.set_unusable_password()
                user.save(update_fields=["password"])

                moderator_role, _ = StaffRole.objects.get_or_create(
                    name="Moderator",
                    defaults={
                        "description": "Chat moderation staff.",
                        "active": True,
                        "is_system_role": True,
                    },
                )

                StaffProfile.objects.create(
                    user=user,
                    designation=moderator_role,
                    status=StaffProfile.Status.INVITED,
                )

                invitation = StaffInvitation.objects.create(
                    user=user,
                    invited_by=request.user,
                    token_hash=token_hash,
                    expires_at=timezone.now() + timedelta(hours=24),
                )

                setup_url = request.build_absolute_uri(
                    reverse(
                        "accounts:staff_invitation_setup",
                        kwargs={"invitation_id": invitation.pk, "token": raw_token},
                    )
                )

                subject = "Sansfrontieres Moderator Account Setup"
                message = (
                    f"Hello {first_name},\n\n"
                    "You have been invited to join Sansfrontieres Chat Moderation as a Moderator.\n\n"
                    "To complete your registration and activate your account, use the secure account setup link below.\n\n"
                    "Account Setup:\n"
                    f"{setup_url}\n\n"
                    "The invitation link is valid for 24 hours and can only be used once. "
                    "During the account setup process, you will be asked to create your password "
                    "and provide the required contact and payment details.\n\n"
                    "If you did not expect this invitation, you may disregard this email.\n\n"
                    "Regards,\n\n"
                    "Sansfrontieres Chat Moderation"
                )

                transaction.on_commit(
                    lambda: send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [email],
                        fail_silently=False,
                    )
                )

            messages.success(
                request,
                f"Invitation sent to {email}.",
            )
            return redirect("accounts:staff_list")
    else:
        form = StaffInvitationForm()

    return render(
        request,
        "accounts/staff_create.html",
        {"form": form},
    )



def staff_invitation_setup(request, invitation_id, token):
    invitation = get_object_or_404(
        StaffInvitation.objects.select_related("user"),
        pk=invitation_id,
    )
    user = invitation.user
    staff_profile = get_object_or_404(StaffProfile, user=user)

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    if invitation.revoked_at or invitation.used_at:
        return render(request, "accounts/staff_invitation_invalid.html", {"reason": "This invitation is no longer valid."}, status=400)

    if invitation.expires_at <= timezone.now():
        return render(request, "accounts/staff_invitation_invalid.html", {"reason": "This invitation has expired. Contact management for a new invitation."}, status=400)

    if invitation.token_hash != token_hash:
        return render(request, "accounts/staff_invitation_invalid.html", {"reason": "This invitation link is invalid."}, status=400)

    if staff_profile.status != StaffProfile.Status.INVITED or user.is_active:
        return render(request, "accounts/staff_invitation_invalid.html", {"reason": "This account is no longer awaiting setup."}, status=400)

    if request.method == "POST":
        form = ModeratorSetupForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user.username = user.email
                user.set_password(form.cleaned_data["password"])
                user.is_active = True
                user.save(update_fields=["username", "password", "is_active"])

                staff_profile.phone_number = form.cleaned_data["phone_number"].strip()
                staff_profile.whatsapp_number = form.cleaned_data["whatsapp_number"].strip()
                staff_profile.mpesa_number = form.cleaned_data["mpesa_number"].strip()
                staff_profile.status = StaffProfile.Status.ACTIVE
                staff_profile.save(update_fields=["phone_number", "whatsapp_number", "mpesa_number", "status", "updated_at"])

                invitation.used_at = timezone.now()
                invitation.save(update_fields=["used_at"])

            messages.success(request, "Your Moderator account has been set up successfully. You can now sign in.")
            return redirect("accounts:login")
    else:
        form = ModeratorSetupForm()

    return render(
        request,
        "accounts/staff_invitation_setup.html",
        {"form": form, "staff_name": user.get_full_name(), "invitation": invitation},
    )

@role_required(*DIRECTOR_ROLES)
@role_required(*DIRECTOR_ROLES)
def staff_edit(request, staff_id):
    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    if request.method == "POST":
        form = StaffEditForm(
            request.POST,
            user=user,
            staff_profile=staff_profile,
        )

        if form.is_valid():
            user.first_name = form.cleaned_data["first_name"]
            user.last_name = form.cleaned_data["last_name"]
            user.email = form.cleaned_data["email"]
            user.role = form.cleaned_data["role"]
            user.save()

            staff_profile.phone_number = form.cleaned_data["phone_number"]
            staff_profile.status = form.cleaned_data["status"]
            staff_profile.notes = form.cleaned_data["notes"]

            if "designation" in form.cleaned_data:
                staff_profile.designation = form.cleaned_data["designation"]

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
            "staff": staff_profile,
            "user": user,
            "staff_user": user,
            "staff_user": user,
        },
    )

@role_required(*DIRECTOR_ROLES)
def staff_revoke_invitation(request, staff_id):
    if request.method != "POST":
        return redirect("accounts:staff_list")

    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    if staff_profile.status != StaffProfile.Status.INVITED or user.is_active:
        messages.error(
            request,
            "Only an invited staff member with a pending setup can have an invitation revoked.",
        )
        return redirect("accounts:staff_list")

    now = timezone.now()

    revoked_count = StaffInvitation.objects.filter(
        user=user,
        used_at__isnull=True,
        revoked_at__isnull=True,
    ).update(revoked_at=now)

    if revoked_count:
        messages.success(
            request,
            f"The invitation for {user.get_full_name() or user.email} has been revoked.",
        )
    else:
        messages.info(
            request,
            "There is no active invitation to revoke for this staff member.",
        )

    return redirect("accounts:staff_list")


@role_required(*DIRECTOR_ROLES)
def staff_resend_invitation(request, staff_id):
    if request.method != "POST":
        return redirect("accounts:staff_list")

    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    if staff_profile.status != StaffProfile.Status.INVITED or user.is_active:
        messages.error(
            request,
            "A new invitation can only be sent to a staff member whose account is still pending setup.",
        )
        return redirect("accounts:staff_list")

    if not user.email:
        messages.error(
            request,
            "This staff member does not have an email address for the invitation.",
        )
        return redirect("accounts:staff_list")

    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    with transaction.atomic():
        StaffInvitation.objects.filter(
            user=user,
            used_at__isnull=True,
            revoked_at__isnull=True,
        ).update(revoked_at=timezone.now())

        invitation = StaffInvitation.objects.create(
            user=user,
            invited_by=request.user,
            token_hash=token_hash,
            expires_at=timezone.now() + timedelta(hours=24),
        )

        setup_url = request.build_absolute_uri(
            reverse(
                "accounts:staff_invitation_setup",
                kwargs={
                    "invitation_id": invitation.pk,
                    "token": raw_token,
                },
            )
        )

        subject = "Sansfrontieres Moderator Account Setup"
        message = (
            f"Hello {user.first_name},\n\n"
            "Your Moderator account invitation has been resent.\n\n"
            "To complete your registration and activate your account, use the secure account setup link below.\n\n"
            "Account Setup:\n"
            f"{setup_url}\n\n"
            "The invitation link is valid for 24 hours and can only be used once. "
            "Your previous invitation link has been invalidated.\n\n"
            "During the account setup process, you will be asked to create your password "
            "and provide the required contact and payment details.\n\n"
            "If you did not expect this invitation, you may disregard this email.\n\n"
            "Regards,\n\n"
            "Sansfrontieres Chat Moderation"
        )

        transaction.on_commit(
            lambda: send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        )

    messages.success(
        request,
        f"Invitation resent to {user.email}. The previous invitation has been invalidated.",
    )
    return redirect("accounts:staff_list")


@role_required(*DIRECTOR_ROLES)
def staff_activate(request, staff_id):
    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    staff_profile.status = StaffProfile.Status.ACTIVE
    staff_profile.suspension_start = None
    staff_profile.suspension_end = None
    staff_profile.suspension_reason = ""
    staff_profile.save(
        update_fields=[
            "status",
            "suspension_start",
            "suspension_end",
            "suspension_reason",
            "updated_at",
        ]
    )

    user.is_active = True
    user.save(update_fields=["is_active"])

    messages.success(
        request,
        f"{user.get_full_name() or user.username} has been activated.",
    )

    return redirect("accounts:staff_list")

@role_required(*DIRECTOR_ROLES)
def staff_suspend(request, staff_id):
    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    if request.method == "POST":
        form = StaffSuspensionForm(request.POST)

        if form.is_valid():
            staff_profile.status = StaffProfile.Status.SUSPENDED
            staff_profile.suspension_start = form.cleaned_data["suspension_start"]
            staff_profile.suspension_end = form.cleaned_data["suspension_end"]
            staff_profile.suspension_reason = form.cleaned_data["suspension_reason"]
            staff_profile.save(
                update_fields=[
                    "status",
                    "suspension_start",
                    "suspension_end",
                    "suspension_reason",
                    "updated_at",
                ]
            )

            user.is_active = False
            user.save(update_fields=["is_active"])

            messages.success(
                request,
                f"{user.get_full_name() or user.username} has been suspended.",
            )

            return redirect("accounts:staff_list")
    else:
        form = StaffSuspensionForm()

    return render(
        request,
        "accounts/staff_suspend.html",
        {
            "form": form,
            "staff": staff_profile,
            "user": user,
        },
    )

@role_required(*DIRECTOR_ROLES)
def staff_terminate(request, staff_id):
    user = get_object_or_404(User, pk=staff_id)
    staff_profile = get_object_or_404(StaffProfile, user=user)

    if request.method == "POST":
        staff_profile.status = StaffProfile.Status.TERMINATED
        staff_profile.save(update_fields=["status", "updated_at"])

        user.is_active = False
        user.save(update_fields=["is_active"])

        messages.success(
            request,
            f"{user.get_full_name() or user.username} has been terminated.",
        )

    return redirect("accounts:staff_list")

def role_list(request):

    roles = (
        StaffRole.objects
        .prefetch_related("staff_profiles")
        .all()
        .order_by("name")
    )

    return render(
        request,
        "accounts/role_list.html",
        {
            "roles": roles,
        },
    )


@role_required(*DIRECTOR_ROLES)
def role_create(request):

    if request.method == "POST":

        # Director manually types the exact role name.
        name = request.POST.get(
            "name",
            "",
        ).strip()

        description = request.POST.get(
            "description",
            "",
        ).strip()

        if not name:

            messages.error(
                request,
                "Please enter a role name.",
            )

        elif StaffRole.objects.filter(
            name__iexact=name
        ).exists():

            messages.error(
                request,
                "A role with this name already exists.",
            )

        else:

            StaffRole.objects.create(
                name=name,
                description=description,
                active=True,
                is_system_role=False,
            )

            messages.success(
                request,
                f"The role '{name}' was created successfully.",
            )

            return redirect(
                "accounts:role_list"
            )

    return render(
        request,
        "accounts/role_create.html",
    )


@role_required(*DIRECTOR_ROLES)
def role_edit(request, role_id):

    role = get_object_or_404(
        StaffRole,
        pk=role_id,
    )

    if request.method == "POST":

        name = request.POST.get(
            "name",
            "",
        ).strip()

        description = request.POST.get(
            "description",
            "",
        ).strip()

        if role.is_system_role:

            if not name:
                name = role.name

            if name.lower() != role.name.lower():

                messages.error(
                    request,
                    (
                        "Director, Manager and Moderator "
                        "system role names cannot be changed."
                    ),
                )

                return render(
                    request,
                    "accounts/role_edit.html",
                    {"role": role},
                )

        else:

            if not name:

                messages.error(
                    request,
                    "Please enter a role name.",
                )

                return render(
                    request,
                    "accounts/role_edit.html",
                    {"role": role},
                )

            duplicate = (
                StaffRole.objects
                .filter(name__iexact=name)
                .exclude(pk=role.pk)
                .exists()
            )

            if duplicate:

                messages.error(
                    request,
                    "A role with this name already exists.",
                )

                return render(
                    request,
                    "accounts/role_edit.html",
                    {"role": role},
                )

            role.name = name

        role.description = description

        role.save()

        messages.success(
            request,
            f"The role '{role.name}' was updated successfully.",
        )

        return redirect(
            "accounts:role_list"
        )

    return render(
        request,
        "accounts/role_edit.html",
        {
            "role": role,
        },
    )


@role_required(*DIRECTOR_ROLES)
def role_toggle(request, role_id):

    if request.method != "POST":
        return redirect("accounts:role_list")

    role = get_object_or_404(
        StaffRole,
        pk=role_id,
    )

    if role.is_system_role:

        messages.error(
            request,
            (
                f"The system role '{role.name}' "
                "cannot be deactivated."
            ),
        )

        return redirect(
            "accounts:role_list"
        )

    if role.staff_profiles.exists():

        messages.error(
            request,
            (
                f"The role '{role.name}' is currently "
                "assigned to staff and cannot be deactivated."
            ),
        )

        return redirect(
            "accounts:role_list"
        )

    role.active = not role.active

    role.save(
        update_fields=[
            "active",
            "updated_at",
        ]
    )

    status = (
        "activated"
        if role.active
        else "deactivated"
    )

    messages.success(
        request,
        f"The role '{role.name}' has been {status}.",
    )

    return redirect(
        "accounts:role_list"
    )







