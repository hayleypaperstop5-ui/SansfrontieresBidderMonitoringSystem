from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models


class PaymentRecord(models.Model):

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_records",
        limit_choices_to={"role": "MODERATOR"},
    )

    coverage_session = models.OneToOneField(
        "coverage.CoverageSession",
        on_delete=models.PROTECT,
        related_name="payment_record",
    )

    chats_responded = models.PositiveIntegerField(
        validators=[
            MinValueValidator(0),
        ],
    )

    payroll_processed_chats = models.PositiveIntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=(
            "Number of this session's chats already consumed by "
            "Player-level payroll processing."
        ),
    )

    notes = models.TextField(
        blank=True,


    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    consumed_by = models.ForeignKey(
        "ModeratorPayment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="consumed_records",
        help_text=(
            "The ModeratorPayment that consumed this record during payroll "
            "processing. Null for unpaid records and for historical rows "
            "consumed before this field existed."
        ),
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = []

    def clean(self):
        super().clean()

        if self.payroll_processed_chats > self.chats_responded:
            raise ValidationError(
                {
                    "payroll_processed_chats": (
                        "Processed payroll chats cannot exceed chats responded."
                    )
                }
            )

class ModeratorPayment(models.Model):

    class PaymentMethod(models.TextChoices):
        WEEKLY_PER_CHAT = "WEEKLY_PER_CHAT", "Weekly / Per Chat"
        MONTHLY = "MONTHLY", "Monthly"

    class RateMethod(models.TextChoices):
        CHAT_TIER = "CHAT_TIER", "Chat Tier"
        PLAYER_CHAT_RATE = "PLAYER_CHAT_RATE", "Player Chat Rate"
        BOTH = "BOTH", "Both"

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="moderator_weekly_payments",
        limit_choices_to={"role": "MODERATOR"},
    )

    payment_week_start = models.DateField()
    payment_week_end = models.DateField()
    payment_date = models.DateField()

    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.WEEKLY_PER_CHAT,
    )

    payable_chats = models.PositiveIntegerField(default=0)
    payroll_processed_chats = models.PositiveIntegerField(
        default=0,
        validators=[
            MinValueValidator(0),
        ],
        help_text=(
            "Number of this session's chats already consumed by "
            "Player-level payroll processing."
        ),
    )

    rate_per_chat = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    paid_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the Director marked this payment as paid.",
    )

    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="moderator_payments_made",
        help_text="Director who recorded the payment.",
    )

    mpesa_reference = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="M-Pesa transaction reference entered by the Director.",
    )

    rate_reconciliation = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Audit trail of rate recalculations applied to this payment. "
            "Each entry records old/new earned amounts, old/new rates, "
            "reason, and timestamp."
        ),
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Amount actually paid. Null until the payment is recorded.",
    )

    rate_method = models.CharField(
        max_length=30,
        choices=RateMethod.choices,
        default=RateMethod.CHAT_TIER,
    )

    chat_tier_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
        help_text=(
            "Historical Chat Tier rate snapshot used when this payment "
            "was processed."
        ),
    )

    player_chat_rate_breakdown = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Historical Player Chat Rate breakdown used when this payment "
            "was processed, keyed by Player."
        ),
    )

    generated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    chat_earnings = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    bonus_earned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    monthly_base_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    earned_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    carried_forward = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    outstanding_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNPAID,
    )

    payment_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_week_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["moderator", "payment_week_start", "payment_week_end"],
                name="unique_moderator_payment_week",
            ),
            # NOTE: mpesa_reference uniqueness removed to support bulk payment
            # (one M-Pesa transaction covering multiple payroll weeks).
            # The audit trail (paid_by, paid_at, amount_paid per row) and
            # the console display prevent accidental double-entry.
            # For stricter reconciliation later, introduce a BulkPaymentBatch
            # model to hold the unique reference.
        ]
        indexes = [
            models.Index(
                fields=["moderator", "payment_week_end"],
                name="mod_payment_week_idx",
            ),
            models.Index(
                fields=["status", "payment_date"],
                name="mod_payment_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.moderator} | "
            f"{self.payment_week_start} - {self.payment_week_end} | "
            f"{self.earned_amount}"
        )

    def delete(self, *args, **kwargs):
        if self.status == self.Status.PAID:
            raise ValidationError("Paid payroll records cannot be deleted.")
        return super().delete(*args, **kwargs)

    def save(self, *args, **kwargs):
        if self.pk:
            previous_status = (
                ModeratorPayment.objects
                .filter(pk=self.pk)
                .values_list("status", flat=True)
                .first()
            )
            if previous_status == self.Status.PAID and self.status != self.Status.PAID:
                raise ValidationError(
                    "A paid payroll record cannot be reverted to unpaid."
                )
        return super().save(*args, **kwargs)


class ManagerPayment(models.Model):

    class PaymentMethod(models.TextChoices):
        COMMISSION = "COMMISSION", "Commission"
        MONTHLY = "MONTHLY", "Monthly"

    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially Paid"
        PAID = "PAID", "Paid"

    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="manager_weekly_payments",
        limit_choices_to={"role": "MANAGER"},
    )

    payment_week_start = models.DateField()
    payment_week_end = models.DateField()
    payment_date = models.DateField()

    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.COMMISSION,
    )

    generated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        validators=[MinValueValidator(0)],
    )

    commission_earned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    monthly_base_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    bonus_earned = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    earned_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    carried_forward = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    outstanding_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UNPAID,
    )

    payment_reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-payment_week_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["manager", "payment_week_start", "payment_week_end"],
                name="unique_manager_payment_week",
            ),
        ]
        indexes = [
            models.Index(
                fields=["manager", "payment_week_end"],
                name="mgr_payment_week_idx",
            ),
            models.Index(
                fields=["status", "payment_date"],
                name="mgr_payment_status_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.manager} | "
            f"{self.payment_week_start} - {self.payment_week_end} | "
            f"{self.earned_amount}"
        )

class PlayerPayrollLedger(models.Model):
    """
    Audit snapshot of a Player's unpaid-chat payroll position for
    a completed payroll period.
    """

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="payroll_ledger_entries",
    )

    payment_week_start = models.DateField()
    payment_week_end = models.DateField()

    opening_carried_forward = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    current_period_chats = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    total_available_chats = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    qualified_chats = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    processed_chats = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    closing_carried_forward = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    chats_remaining_to_qualification = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = [
            "-payment_week_end",
            "player_id",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "player",
                    "payment_week_start",
                    "payment_week_end",
                ],
                name="player_payroll_ledger_unique",
            ),
        ]
        indexes = [
            models.Index(
                fields=[
                    "payment_week_start",
                    "payment_week_end",
                ],
                name="player_payroll_ledger_idx",
            ),
        ]

class PaymentSettings(models.Model):
    """
    Current Director-controlled payment configuration.

    Weekly payment records keep their own historical snapshots, so
    changing these settings does not alter previously processed payroll.
    """

    class ModeratorPaymentMethod(models.TextChoices):
        WEEKLY_PER_CHAT = "WEEKLY_PER_CHAT", "Weekly / Per Chat"
        MONTHLY = "MONTHLY", "Monthly"

    class ManagerPaymentMethod(models.TextChoices):
        COMMISSION = "COMMISSION", "Commission"
        MONTHLY = "MONTHLY", "Monthly"

    moderator_rate_method = models.CharField(
        max_length=30,
        choices=ModeratorPayment.RateMethod.choices,
        default=ModeratorPayment.RateMethod.CHAT_TIER,
        help_text=(
            "Rate method used when calculating qualifying Moderator "
            "chat earnings."
        ),
    )

    minimum_chats_per_player = models.PositiveIntegerField(
        default=700,
        help_text=(
            "Minimum combined chats a Player must receive in a payment "
            "week for those chats to qualify for Moderator payment."
        ),
    )

    payment_day = models.PositiveSmallIntegerField(
        default=3,
        help_text="Python weekday number: Monday=0 through Sunday=6.",
    )

    moderator_payment_method = models.CharField(
        max_length=30,
        choices=ModeratorPaymentMethod.choices,
        default=ModeratorPaymentMethod.WEEKLY_PER_CHAT,
    )

    moderator_monthly_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    manager_payment_method = models.CharField(
        max_length=20,
        choices=ManagerPaymentMethod.choices,
        default=ManagerPaymentMethod.COMMISSION,
    )

    manager_commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10,
        validators=[MinValueValidator(0)],
    )

    manager_monthly_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment Settings"
        verbose_name_plural = "Payment Settings"

    def clean(self):
        super().clean()

        if not 0 <= self.payment_day <= 6:
            raise ValidationError(
                {
                    "payment_day": (
                        "Payment day must be between 0 and 6 "
                        "(Monday=0, Sunday=6)."
                    )
                }
            )

        if self.manager_commission_percentage > 100:
            raise ValidationError(
                {
                    "manager_commission_percentage": (
                        "Manager commission percentage cannot exceed 100%."
                    )
                }
            )

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return "Payment Settings"









