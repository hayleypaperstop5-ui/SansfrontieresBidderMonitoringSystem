from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class ChatBonusTier(models.Model):
    """
    Director-controlled rule defining when a Moderator qualifies
    for a chat-volume bonus.
    """

    minimum_chats = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
    )

    maximum_chats = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )

    bonus_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Bonus amount in KES.",
    )

    qualifying_window_hours = models.PositiveIntegerField(
        default=24,
        validators=[MinValueValidator(1)],
        help_text="Number of hours within which the Moderator must reach the chat threshold.",
    )

    active = models.BooleanField(default=True)

    effective_from = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            "minimum_chats",
            "id",
        ]
        indexes = [
            models.Index(
                fields=["active", "minimum_chats"],
                name="bonus_tier_active_min_idx",
            ),
            models.Index(
                fields=["effective_from"],
                name="bonus_tier_effective_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.maximum_chats is not None
            and self.maximum_chats < self.minimum_chats
        ):
            raise ValidationError(
                {
                    "maximum_chats": (
                        "Maximum chats must be greater than or equal "
                        "to minimum chats."
                    )
                }
            )

        overlapping = ChatBonusTier.objects.filter(
            active=True,
            qualifying_window_hours=self.qualifying_window_hours,
        ).exclude(pk=self.pk)

        for tier in overlapping:
            if tier.effective_from != self.effective_from:
                continue

            self_max = (
                self.maximum_chats
                if self.maximum_chats is not None
                else 10**18
            )

            tier_max = (
                tier.maximum_chats
                if tier.maximum_chats is not None
                else 10**18
            )

            if (
                tier.minimum_chats <= self_max
                and tier_max >= self.minimum_chats
            ):
                raise ValidationError(
                    "This chat range overlaps with another active bonus tier "
                    "using the same qualifying window and effective date."
                )

    def __str__(self):
        if self.maximum_chats is None:
            chat_range = f"{self.minimum_chats}+ chats"
        else:
            chat_range = (
                f"{self.minimum_chats}-{self.maximum_chats} chats"
            )

        return (
            f"{chat_range} | "
            f"{self.bonus_amount} KES | "
            f"{self.qualifying_window_hours}h"
        )


class BonusAward(models.Model):
    """
    Permanent historical record of a bonus actually awarded to a Moderator
    for a specific Player within a 24-hour qualification window.
    """

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="bonus_awards",
        limit_choices_to={"role": "MODERATOR"},
    )

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="bonus_awards",
        null=True,
        blank=True,
    )

    qualifying_report = models.ForeignKey(
        "coverage.EndOfSessionReport",
        on_delete=models.PROTECT,
        related_name="bonus_awards",
    )

    bonus_tier = models.ForeignKey(
        ChatBonusTier,
        on_delete=models.PROTECT,
        related_name="awards",
    )

    bonus_date = models.DateField(
        help_text="Business date on which the bonus was awarded.",
    )

    qualifying_window_start = models.DateTimeField()

    qualifying_window_end = models.DateTimeField()

    chats_counted = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
    )

    minimum_chats_snapshot = models.PositiveIntegerField()

    maximum_chats_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    qualifying_window_hours_snapshot = models.PositiveIntegerField()

    bonus_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Actual bonus amount awarded in KES.",
    )

    awarded_at = models.DateTimeField(
        auto_now_add=True,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-bonus_date",
            "-awarded_at",
        ]
        indexes = [
            models.Index(
                fields=["moderator", "player", "bonus_date"],
                name="bonus_award_mod_p_date_idx",
            ),
            models.Index(
                fields=["bonus_date"],
                name="bonus_award_date_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["moderator", "player", "qualifying_window_start", "qualifying_window_end"],
                name="unique_bonus_per_moderator_player_window",
            )
        ]

    def clean(self):
        super().clean()

        if self.qualifying_window_start > self.qualifying_window_end:
            raise ValidationError(
                {
                    "qualifying_window_end": (
                        "The qualifying window end cannot be earlier "
                        "than the window start."
                    )
                }
            )

        if self.chats_counted < self.minimum_chats_snapshot:
            raise ValidationError(
                {
                    "chats_counted": (
                        "Chats counted cannot be below the minimum "
                        "chat threshold."
                    )
                }
            )

    def __str__(self):
        player_str = f" | Player: {self.player}" if self.player else ""
        return (
            f"{self.moderator}{player_str} | "
            f"{self.bonus_date} | "
            f"{self.bonus_amount} KES"
        )
