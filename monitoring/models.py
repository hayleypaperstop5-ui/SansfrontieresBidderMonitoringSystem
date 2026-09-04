from django.conf import settings
from django.db import models


class ChatSubmission(models.Model):

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        REVIEWED = "REVIEWED", "Reviewed"
        FLAGGED = "FLAGGED", "Flagged"

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="chat_submissions",
        limit_choices_to={
            "role": "MODERATOR",
        },
    )

    chat_reference = models.CharField(
        max_length=100,
    )

    chat_content = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.SUBMITTED,
    )

    submitted_at = models.DateTimeField(
        auto_now_add=True,
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new:
            from accounts.models import StaffProfile

            StaffProfile.objects.filter(
                user=self.moderator,
            ).update(
                last_chat_submitted_at=self.submitted_at,
            )

    def __str__(self):
        return (
            f"{self.chat_reference} - "
            f"{self.moderator.get_full_name() or self.moderator.username}"
        )
