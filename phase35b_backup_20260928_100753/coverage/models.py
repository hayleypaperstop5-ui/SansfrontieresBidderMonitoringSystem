from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q


class CoverageSession(models.Model):
    class SessionType(models.TextChoices):
        DAY = "DAY", "Day"
        NIGHT = "NIGHT", "Night"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACTIVE = "ACTIVE", "Active"
        REPLACEMENT_REQUESTED = "REPLACEMENT_REQUESTED", "Replacement Requested"
        HANDOVER = "HANDOVER", "Handover"
        AWAITING_REPORT = "AWAITING_REPORT", "Awaiting Report"
        EXPIRED = "EXPIRED", "Expired"
        COMPLETED = "COMPLETED", "Completed"
        MISSED = "MISSED", "Missed"
        CANCELLED = "CANCELLED", "Cancelled"

    class ClosureReason(models.TextChoices):
        NORMAL = "NORMAL", "Normal Sign-out"
        AUTOMATIC = "AUTOMATIC", "Automatic Session Closure"
        REPLACED = "REPLACED", "Replaced by Another Moderator"
        MANAGER_OVERRIDE = "MANAGER_OVERRIDE", "Manager Override"
        CANCELLED = "CANCELLED", "Cancelled"

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="coverage_sessions",
    )

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="coverage_sessions",
        limit_choices_to={"role": "MODERATOR"},
    )

    operating_date = models.DateField()

    session_type = models.CharField(
        max_length=10,
        choices=SessionType.choices,
    )

    signed_in_at = models.DateTimeField(null=True, blank=True)
    sign_in_deadline_at = models.DateTimeField(null=True, blank=True, help_text="Deadline by which the assigned Moderator must sign in.")

    scheduled_close_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="System calculated boundary for automatic session closure.",
    )

    signed_out_at = models.DateTimeField(null=True, blank=True)

    closure_reason = models.CharField(
        max_length=30,
        choices=ClosureReason.choices,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.OPEN,
    )

    replacement_requested_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    replacement_moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="replacement_coverage_sessions",
        limit_choices_to={"role": "MODERATOR"},
        null=True,
        blank=True,
    )

    replacement_session = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        related_name="replaced_session",
        null=True,
        blank=True,
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-operating_date", "session_type", "-created_at"]
        indexes = [
            models.Index(
                fields=["player", "operating_date", "session_type"],
                name="coverage_player_date_type_idx",
            ),
            models.Index(
                fields=["moderator", "operating_date", "session_type"],
                name="coverage_mod_date_type_idx",
            ),
            models.Index(
                fields=["status"],
                name="coverage_status_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["player"],
                condition=Q(
                    status__in=[
                        "OPEN",
                        "ACTIVE",
                        "REPLACEMENT_REQUESTED",
                        "HANDOVER",
                    ]
                ),
                name="unique_active_coverage_per_player",
            ),
            models.UniqueConstraint(
                fields=["moderator"],
                condition=Q(
                    status__in=[
                        "OPEN",
                        "ACTIVE",
                        "REPLACEMENT_REQUESTED",
                        "HANDOVER",
                    ]
                ),
                name="unique_active_player_per_moderator",
            ),
        ]

    def clean(self):
        super().clean()

        if self.moderator_id:
            moderator_role = getattr(self.moderator, "role", None)
            if moderator_role != "MODERATOR":
                raise ValidationError(
                    {"moderator": "Coverage sessions can only be assigned to Moderators."}
                )

        if self.replacement_moderator_id:
            replacement_role = getattr(self.replacement_moderator, "role", None)
            if replacement_role != "MODERATOR":
                raise ValidationError(
                    {
                        "replacement_moderator": (
                            "Replacement coverage can only be assigned to a Moderator."
                        )
                    }
                )

        if self.signed_out_at and self.signed_in_at:
            if self.signed_out_at < self.signed_in_at:
                raise ValidationError(
                    {"signed_out_at": "Sign-out time cannot be earlier than sign-in time."}
                )

        if self.replacement_moderator_id and self.replacement_moderator_id == self.moderator_id:
            raise ValidationError(
                {
                    "replacement_moderator": (
                        "A Moderator cannot replace their own coverage session."
                    )
                }
            )

    def __str__(self):
        return (
            f"{self.player} | {self.moderator} | "
            f"{self.get_session_type_display()} | "
            f"{self.operating_date}"
        )


class EndOfSessionReport(models.Model):
    coverage_session = models.OneToOneField(
        CoverageSession,
        on_delete=models.PROTECT,
        related_name="end_of_session_report",
    )

    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="end_of_session_reports",
        limit_choices_to={"role": "MODERATOR"},
    )

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="end_of_session_reports",
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
        upload_to="coverage_reports/%Y/%m/%d/",
        blank=True,
        null=True,
    )

    comments = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return (
            f"{self.player} | {self.moderator} | "
            f"{self.coverage_session.get_session_type_display()} | "
            f"{self.coverage_session.operating_date}"
        )


class ReportCompliance(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        COMPLETED_ON_TIME = "COMPLETED_ON_TIME", "Completed On Time"
        OVERDUE = "OVERDUE", "Overdue"
        LATE = "LATE", "Late"

    coverage_session = models.OneToOneField(
        CoverageSession,
        on_delete=models.PROTECT,
        related_name="report_compliance",
    )

    report = models.OneToOneField(
        EndOfSessionReport,
        on_delete=models.PROTECT,
        related_name="report_compliance",
        null=True,
        blank=True,
    )

    signed_out_at = models.DateTimeField()
    report_deadline = models.DateTimeField()
    report_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    overdue_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-signed_out_at"]
        indexes = [
            models.Index(
                fields=["status", "report_deadline"],
                name="report_comp_status_deadline",
            ),
            models.Index(
                fields=["signed_out_at"],
                name="report_comp_signed_out_idx",
            ),
        ]

    def clean(self):
        super().clean()

        if self.report_deadline and self.signed_out_at:
            if self.report_deadline < self.signed_out_at:
                raise ValidationError(
                    {
                        "report_deadline": (
                            "Report deadline cannot be earlier than sign-out time."
                        )
                    }
                )

        if self.report_submitted_at and self.report_submitted_at < self.signed_out_at:
            raise ValidationError(
                {
                    "report_submitted_at": (
                        "Report submission cannot be earlier than sign-out time."
                    )
                }
            )

    def __str__(self):
        return (
            f"{self.coverage_session} | "
            f"{self.get_status_display()}"
        )

class CoverageAlert(models.Model):
    class AlertType(models.TextChoices):
        PLAYER_UNCOVERED = "PLAYER_UNCOVERED", "Player Uncovered"
        COVERAGE_MISSED = "COVERAGE_MISSED", "Coverage Missed"
        ESCALATION = "ESCALATION", "Escalation"

    class Severity(models.TextChoices):
        WARNING = "WARNING", "Warning"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        RESOLVED = "RESOLVED", "Resolved"
        ESCALATED = "ESCALATED", "Escalated"

    player = models.ForeignKey(
        "players.Player",
        on_delete=models.PROTECT,
        related_name="coverage_alerts",
    )

    alert_type = models.CharField(
        max_length=30,
        choices=AlertType.choices,
        default=AlertType.PLAYER_UNCOVERED,
    )

    severity = models.CharField(
        max_length=20,
        choices=Severity.choices,
        default=Severity.CRITICAL,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.OPEN,
    )

    operating_date = models.DateField()

    session_type = models.CharField(
        max_length=10,
        choices=CoverageSession.SessionType.choices,
    )

    started_at = models.DateTimeField()

    last_reminder_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    next_reminder_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    reminder_count = models.PositiveIntegerField(
        default=0,
    )

    acknowledged_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_coverage_alerts",
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_coverage_alerts",
    )

    escalated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["player", "status"],
                name="cov_alert_player_status_idx",
            ),
            models.Index(
                fields=["status", "next_reminder_at"],
                name="cov_alert_reminder_idx",
            ),
            models.Index(
                fields=["operating_date", "session_type"],
                name="cov_alert_operation_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["player", "operating_date", "session_type"],
                condition=models.Q(
                    status__in=["OPEN", "ACKNOWLEDGED", "ESCALATED"]
                ),
                name="unique_open_coverage_alert",
            ),
        ]

    def __str__(self):
        return (
            f"{self.player} - {self.get_alert_type_display()} "
            f"({self.get_status_display()})"
        )
