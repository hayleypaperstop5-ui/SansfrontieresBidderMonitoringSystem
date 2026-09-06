from django.contrib import messages
from django.shortcuts import redirect, render

from accounts.decorators import role_required
from accounts.permissions import MANAGER_ROLES, RATE_MANAGEMENT_ROLES
from coverage.models import CoverageSession

from .forms import ChatRateTierForm, PlayerCreationForm, PlayerEditForm
from .models import ChatRateTier, Player


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
def chat_rate_list(request):

    rate_tiers = ChatRateTier.objects.all()

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
