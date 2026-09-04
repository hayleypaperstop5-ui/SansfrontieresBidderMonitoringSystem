from django.conf import settings
from django.db import models


class Shift(models.Model):
    class ShiftType(models.TextChoices):
        DAY = "DAY", "Day Shift"
        NIGHT = "NIGHT", "Night Shift"

    class Status(models.TextChoices):
        SCHEDULED = "SCHEDULED", "Scheduled"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        AWAITING_REPORT = "AWAITING_REPORT", "Awaiting Report"
        REPORT_OVERDUE = "REPORT_OVERDUE", "Report Overdue"
        COMPLETED = "COMPLETED", "Completed"
        MISSED = "MISSED", "Missed"
        CANCELLED = "CANCELLED", "Cancelled"

    date = models.DateField()
    shift_type = models.CharField(
        max_length=10,
        choices=ShiftType.choices,
        default=ShiftType.DAY,
    )

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="shifts",
    )

    primary_moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="primary_shifts",
        limit_choices_to={"role": "MODERATOR"},
    )

    substitute = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="substitute_shifts",
        limit_choices_to={"role": "MODERATOR"},
        null=True,
        blank=True,
    )

    scheduled_start = models.TimeField()
    scheduled_end = models.TimeField()

    actual_worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="worked_shifts",
        limit_choices_to={"role": "MODERATOR"},
        null=True,
        blank=True,
    )

    actual_sign_in = models.DateTimeField(
        null=True,
        blank=True,
    )

    actual_sign_out = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SCHEDULED,
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "scheduled_start"]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["player", "date"]),
            models.Index(fields=["primary_moderator", "date"]),
        ]

    def __str__(self):
        return (
            f"{self.date} | Player {self.player.player_number} - "
            f"{self.player.name} | "
            f"{self.primary_moderator.get_full_name() or self.primary_moderator.username}"
        )