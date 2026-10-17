from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class ShiftReport(models.Model):
    shift = models.OneToOneField(
        "shifts.Shift",
        on_delete=models.PROTECT,
        related_name="report",
    )

    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="shift_reports",
        limit_choices_to={
            "role": "MODERATOR",
        },
    )

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="shift_reports",
    )

    chats_responded = models.PositiveIntegerField(
        validators=[MinValueValidator(0)],
    )

    account_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(10),
        ],
    )

    screenshot = models.ImageField(
        upload_to="shift_reports/%Y/%m/%d/",
        blank=True,
        null=True,
    )

    comments = models.TextField(
        blank=True,
    )

    submitted_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return (
            f"{self.shift.date} | "
            f"Player {self.player.player_number} | "
            f"{self.worker.get_full_name() or self.worker.username} | "
            f"{self.chats_responded} chats"
        )
