from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from accounts.permissions import RATE_MANAGEMENT_ROLES

from .forms import ChatBonusTierForm
from .models import ChatBonusTier


@role_required(*RATE_MANAGEMENT_ROLES)
def bonus_settings(request):
    active_bonus_tier = (
        ChatBonusTier.objects
        .filter(
            active=True,
            qualifying_window_hours=24,
        )
        .order_by("-effective_from", "-id")
        .first()
    )

    bonus_history = (
        ChatBonusTier.objects
        .filter(
            qualifying_window_hours=24,
        )
        .order_by("-effective_from", "-id")
    )

    return render(
        request,
        "bonuses/bonus_settings.html",
        {
            "active_bonus_tier": active_bonus_tier,
            "bonus_history": bonus_history,
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def bonus_settings_create(request):
    if request.method == "POST":
        form = ChatBonusTierForm(request.POST)

        if form.is_valid():
            with transaction.atomic():
                ChatBonusTier.objects.filter(
                    active=True,
                    qualifying_window_hours=24,
                ).update(active=False)

                bonus = form.save(commit=False)

                # The qualification window remains fixed at 24 hours.
                bonus.maximum_chats = None
                bonus.qualifying_window_hours = 24
                bonus.active = True
                bonus.save()

            messages.success(
                request,
                f"Moderator bonus saved: "
                f"{bonus.minimum_chats:,} chats within 24 hours "
                f"for KES {bonus.bonus_amount:,.2f}.",
            )

            return redirect("bonuses:bonus_settings")
    else:
        form = ChatBonusTierForm(
            initial={
                "minimum_chats": 500,
                "active": True,
            }
        )

    return render(
        request,
        "bonuses/bonus_settings_form.html",
        {
            "form": form,
            "page_title": "Configure Moderator Bonus",
            "submit_label": "Save Bonus",
        },
    )


@role_required(*RATE_MANAGEMENT_ROLES)
def bonus_settings_edit(request, bonus_id):
    bonus = get_object_or_404(
        ChatBonusTier,
        id=bonus_id,
        qualifying_window_hours=24,
    )

    if request.method == "POST":
        form = ChatBonusTierForm(request.POST, instance=bonus)

        if form.is_valid():
            with transaction.atomic():
                ChatBonusTier.objects.filter(
                    active=True,
                    qualifying_window_hours=24,
                ).exclude(id=bonus.id).update(active=False)

                bonus = form.save(commit=False)

                # The qualification window remains fixed at 24 hours.
                bonus.maximum_chats = None
                bonus.qualifying_window_hours = 24
                bonus.save()

            messages.success(
                request,
                f"Moderator bonus updated: "
                f"{bonus.minimum_chats:,} chats within 24 hours "
                f"for KES {bonus.bonus_amount:,.2f}.",
            )

            return redirect("bonuses:bonus_settings")
    else:
        form = ChatBonusTierForm(instance=bonus)

    return render(
        request,
        "bonuses/bonus_settings_form.html",
        {
            "form": form,
            "page_title": "Edit Moderator Bonus",
            "submit_label": "Save Changes",
            "bonus": bonus,
        },
    )
