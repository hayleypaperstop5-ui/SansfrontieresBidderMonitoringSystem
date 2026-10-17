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

    login_username = models.CharField(
        max_length=150,
        blank=True,
        default="",
        help_text="The login username the moderator uses to access this player's account.",
    )

    login_password_encrypted = models.CharField(
        max_length=512,
        blank=True,
        default="",
        help_text="Encrypted player login password. Never displayed in plain text outside the moderator popup.",
    )

    login_notes = models.TextField(
        blank=True,
        default="",
        help_text="Optional notes about the player's login (2FA, recovery email, etc.).",
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

    @property
    def login_password(self):
        """Decrypt and return the player's login password."""
        if not self.login_password_encrypted:
            return ""
        from accounts.credential_crypto import decrypt_value
        try:
            return decrypt_value(self.login_password_encrypted)
        except Exception:
            return ""

    @login_password.setter
    def login_password(self, value):
        """Encrypt and store the player's login password."""
        from accounts.credential_crypto import encrypt_value
        if value:
            self.login_password_encrypted = encrypt_value(value)
        else:
            self.login_password_encrypted = ""

    def __str__(self):
        return f"Player {self.player_number} - {self.name}"


class PlayerChatRateTier(models.Model):

    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="chat_rate_tiers",
    )

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
        ordering = ["player", "minimum_chats"]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.maximum_chats is not None
            and self.maximum_chats < self.minimum_chats
        ):
            raise ValidationError(
                "Maximum chats must be greater than or equal to minimum chats."
            )

        if not self.active:
            return

        overlapping = PlayerChatRateTier.objects.filter(
            player=self.player,
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
                    "This Player chat range overlaps with another active rate tier."
                )

    def __str__(self):
        if self.maximum_chats is None:
            chat_range = f"{self.minimum_chats}+ chats"
        else:
            chat_range = f"{self.minimum_chats}-{self.maximum_chats} chats"

        return (
            f"Player {self.player.player_number} | "
            f"{chat_range} | Rate {self.rate_per_chat}"
        )


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
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(maximum_chats__isnull=True)
                    | models.Q(minimum_chats__lt=models.F("maximum_chats"))
                    | models.Q(minimum_chats=models.F("maximum_chats"))
                ),
                name="chat_rate_tier_min_lte_max_or_unbounded",
            ),
        ]

    def clean(self):
        from django.core.exceptions import ValidationError

        if (
            self.maximum_chats is not None
            and self.maximum_chats < self.minimum_chats
        ):
            raise ValidationError(
                "Maximum chats must be greater than or equal to minimum chats."
            )

        # Inactive tiers are historical/disabled and may freely overlap
        # active tiers — they do not participate in rate lookups.
        if not self.active:
            return

        # Only check overlap against tiers that could be applied at the
        # same operating date. Tiers with different non-null effective_from
        # dates are historical versions, not conflicts.
        overlapping = ChatRateTier.objects.filter(active=True).exclude(pk=self.pk)
        if self.effective_from is None:
            overlapping = overlapping.filter(effective_from__isnull=True)
        else:
            overlapping = overlapping.filter(
                models.Q(effective_from__isnull=True)
                | models.Q(effective_from=self.effective_from)
            )
        overlapping = overlapping.filter(
            minimum_chats__lte=(
                self.maximum_chats
                if self.maximum_chats is not None
                else 10**18
            ),
        )

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


    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        if self.maximum_chats is None:
            chat_range = f"{self.minimum_chats}+ chats"
        else:
            chat_range = f"{self.minimum_chats}-{self.maximum_chats} chats"

        return f"{chat_range} | Rate {self.rate_per_chat}"


class CredentialDisclosure(models.Model):
    """
    Tracks which moderator has been shown a player's login credentials
    and when they acknowledged them.
    """

    moderator = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="credential_disclosures",
    )

    player = models.ForeignKey(
        Player,
        on_delete=models.CASCADE,
        related_name="credential_disclosures",
    )

    coverage_session = models.ForeignKey(
        "coverage.CoverageSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="credential_disclosures",
    )

    disclosed_at = models.DateTimeField(
        auto_now_add=True,
    )

    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-disclosed_at"]
        indexes = [
            models.Index(
                fields=["moderator", "acknowledged_at"],
                name="cred_disc_mod_ack_idx",
            ),
        ]

    def __str__(self):
        status = "acknowledged" if self.acknowledged_at else "unacknowledged"
        return f"{self.moderator} -> {self.player} ({status})"
