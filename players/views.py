from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.decorators import role_required
from accounts.permissions import MANAGER_ROLES, RATE_MANAGEMENT_ROLES
from coverage.models import CoverageSession

from .forms import ChatRateTierForm, PlayerCreationForm, PlayerEditForm, PlayerChatRateTierForm
from .models import ChatRateTier, Player, PlayerChatRateTier


@role_required(*MANAGER_ROLES)
def player_list(request):

    players = Player.objects.all()

    active_players_count = players.filter(
        status=Player.Status.ACTIVE
    ).count()

    return render(
        request,
        "players/player_list.html",
        {
            "players": players,
            "active_players_count": active_players_count,
        },
    )


@role_required(*MANAGER_ROLES)
def player_create(request):

    if request.method == "POST":

        form = PlayerCreationForm(request.POST)

        if form.is_valid():

            player = form.save()

            messages.success(
                request,
                f"Player {player.player_number} created successfully.",
            )

            return redirect("players:player_list")

    else:

        form = PlayerCreationForm()

    return render(
        request,
        "players/player_create.html",
        {
            "form": form,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def player_chat_rate_list(request):
    """
    Director-only management page for Player-specific chat rates.
    """
    rate_tiers = (
        PlayerChatRateTier.objects
        .select_related("player")
        .order_by(
            "player__player_number",
            "minimum_chats",
            "-effective_from",
            "-id",
        )
    )

    players = Player.objects.all().order_by("player_number")

    return render(
        request,
        "players/player_chat_rate_list.html",
        {
            "rate_tiers": rate_tiers,
            "players": players,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def player_chat_rate_create(request):
    """
    Director-only creation of a Player-specific chat rate tier.
    """
    if request.method == "POST":
        form = PlayerChatRateTierForm(request.POST)

        if form.is_valid():
            rate_tier = form.save()
            messages.success(
                request,
                (
                    f"Player {rate_tier.player.player_number} "
                    "chat rate tier created successfully."
                ),
            )
            return redirect("players:player_chat_rate_list")
    else:
        form = PlayerChatRateTierForm()

    return render(
        request,
        "players/player_chat_rate_form.html",
        {
            "form": form,
            "is_edit": False,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def player_chat_rate_edit(request, rate_id):
    """
    Director-only editing of a Player-specific chat rate tier.
    """
    rate_tier = PlayerChatRateTier.objects.get(pk=rate_id)

    if request.method == "POST":
        form = PlayerChatRateTierForm(
            request.POST,
            instance=rate_tier,
        )

        if form.is_valid():
            rate_tier = form.save()
            messages.success(
                request,
                (
                    f"Player {rate_tier.player.player_number} "
                    "chat rate tier updated successfully."
                ),
            )
            return redirect("players:player_chat_rate_list")
    else:
        form = PlayerChatRateTierForm(instance=rate_tier)

    return render(
        request,
        "players/player_chat_rate_form.html",
        {
            "form": form,
            "rate_tier": rate_tier,
            "is_edit": True,
        },
    )

@role_required(*RATE_MANAGEMENT_ROLES)
def chat_rate_list(request):

    rate_tiers = ChatRateTier.objects.all()
    active_tiers = rate_tiers.filter(active=True).count()

    return render(
        request,
        "players/chat_rate_list.html",
        {
            "rate_tiers": rate_tiers,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def chat_rate_create(request):

    if request.method == "POST":

        form = ChatRateTierForm(request.POST)

        if form.is_valid():

            rate_tier = form.save()

            messages.success(
                request,
                (
                    f"Chat rate tier "
                    f"{rate_tier.minimum_chats}-"
                    f"{rate_tier.maximum_chats or 'plus'} chats "
                    "created successfully."
                ),
            )

            return redirect("players:chat_rate_list")

    else:

        form = ChatRateTierForm()

    return render(
        request,
        "players/chat_rate_form.html",
        {
            "form": form,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def chat_rate_edit(request, rate_id):

    from django.shortcuts import get_object_or_404 as _g404
    rate_tier = _g404(ChatRateTier, pk=rate_id)

    if request.method == "POST":

        form = ChatRateTierForm(
            request.POST,
            instance=rate_tier,
        )

        if form.is_valid():

            rate_tier = form.save()

            messages.success(
                request,
                (
                    f"Chat rate tier "
                    f"{rate_tier.minimum_chats}-"
                    f"{rate_tier.maximum_chats or 'plus'} chats "
                    "was updated successfully."
                ),
            )

            return redirect("players:chat_rate_list")

    else:

        form = ChatRateTierForm(instance=rate_tier)

    return render(
        request,
        "players/chat_rate_form.html",
        {
            "form": form,
            "rate_tier": rate_tier,
            "is_edit": True,
        },
    )

@role_required(*MANAGER_ROLES)
def player_edit(request, player_id):

    player = Player.objects.get(pk=player_id)

    if request.method == "POST":

        form = PlayerEditForm(
            request.POST,
            instance=player,
        )

        if form.is_valid():

            player = form.save()

            messages.success(
                request,
                f"Player {player.player_number} updated successfully.",
            )

            return redirect("players:player_list")

    else:

        form = PlayerEditForm(instance=player)

    return render(
        request,
        "players/player_edit.html",
        {
            "form": form,
            "player": player,
        },
    )


@role_required(*MANAGER_ROLES)
def player_activate(request, player_id):

    player = Player.objects.get(pk=player_id)

    player.status = Player.Status.ACTIVE
    player.save(update_fields=["status", "updated_at"])

    messages.success(
        request,
        f"Player {player.player_number} activated successfully.",
    )

    return redirect("players:player_list")


@role_required(*MANAGER_ROLES)
def player_deactivate(request, player_id):

    player = Player.objects.get(pk=player_id)

    active_coverage_exists = CoverageSession.objects.filter(
        player=player,
        status__in=[
            CoverageSession.Status.OPEN,
            CoverageSession.Status.ACTIVE,
            CoverageSession.Status.REPLACEMENT_REQUESTED,
            CoverageSession.Status.HANDOVER,
        ],
    ).exists()

    if active_coverage_exists:

        messages.error(
            request,
            (
                f"Player {player.player_number} cannot be deactivated "
                "while a coverage session is assigned. "
                "Resolve the current coverage first."
            ),
        )

        return redirect("players:player_list")

    player.status = Player.Status.INACTIVE
    player.save(update_fields=["status", "updated_at"])

    messages.success(
        request,
        f"Player {player.player_number} deactivated successfully.",
    )

    return redirect("players:player_list")

@role_required(*RATE_MANAGEMENT_ROLES)
def chat_rate_delete(request, rate_id):
    """Delete a global ChatRateTier with a confirmation prompt."""
    from .models import ChatRateTier as _CRT

    tier = _CRT.objects.filter(pk=rate_id).first()
    if not tier:
        messages.error(request, "Rate tier not found.")
        return redirect("players:chat_rate_list")

    if request.method != "POST":
        # GET — show confirmation page (or redirect; simplest is to reject GET)
        messages.info(request, "To delete a rate tier, use the Delete button on the rate list.")
        return redirect("players:chat_rate_list")

    label = f"{tier.minimum_chats}-{tier.maximum_chats or 'plus'} chats at KES {tier.rate_per_chat}"
    tier.delete()
    messages.success(request, f"Rate tier ({label}) deleted.")
    return redirect("players:chat_rate_list")
