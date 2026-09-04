from django.db import models
from django.core.validators import MinValueValidator


class Player(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    player_number = models.PositiveSmallIntegerField(
        unique=True,
        validators=[
            MinValueValidator(1),
        ],
    )

    name = models.CharField(
        max_length=150,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["player_number"]

    def __str__(self):
        return f"Player {self.player_number} - {self.name}"


class ChatRateTier(models.Model):

    minimum_chats = models.PositiveIntegerField(
        validators=[
            MinValueValidator(0),
        ],
    )

    maximum_chats = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0),
        ],
    )

    rate_per_chat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(0),
        ],
    )

    active = models.BooleanField(
        default=True,
    )

    effective_from = models.DateField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["minimum_chats"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.maximum_chats is not None
            and self.maximum_chats < self.minimum_chats
        ):
            raise ValidationError(
                "Maximum chats must be greater than or equal to minimum chats."
            )

        overlapping = ChatRateTier.objects.filter(
            active=True,
            minimum_chats__lte=(
                self.maximum_chats
                if self.maximum_chats is not None
                else 10**18
            ),
        ).exclude(pk=self.pk)

        for tier in overlapping:
            if tier.maximum_chats is None:
                overlaps = True
            elif self.maximum_chats is None:
                overlaps = tier.maximum_chats >= self.minimum_chats
            else:
                overlaps = (
                    tier.minimum_chats <= self.maximum_chats
                    and tier.maximum_chats >= self.minimum_chats
                )

            if overlaps:
                raise ValidationError(
                    "This chat range overlaps with another active rate tier."
                )

    def __str__(self):
        if self.maximum_chats is None:
            chat_range = f"{self.minimum_chats}+ chats"
        else:
            chat_range = f"{self.minimum_chats}-{self.maximum_chats} chats"

        return f"{chat_range} | Rate {self.rate_per_chat}"
