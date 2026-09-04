from django.conf import settings
from django.db import models


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        OVERDUE_SHIFT_REPORT = (
            "OVERDUE_SHIFT_REPORT",
            "Overdue Shift Report",
        )
        SHIFT_REPLACEMENT = (
            "SHIFT_REPLACEMENT",
            "Shift Replacement Required",
        )
        GENERAL = (
            "GENERAL",
            "General Notification",
        )

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    notification_type = models.CharField(
        max_length=40,
        choices=NotificationType.choices,
        default=NotificationType.GENERAL,
    )

    title = models.CharField(
        max_length=200,
    )

    message = models.TextField()

    shift = models.ForeignKey(
        "shifts.Shift",
        on_delete=models.CASCADE,
        related_name="notifications",
        null=True,
        blank=True,
    )

    is_read = models.BooleanField(
        default=False,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.recipient}"
