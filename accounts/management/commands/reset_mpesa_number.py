"""
Management command to reset a moderator's M-Pesa number with a required
reason, notify the moderator, and log the reset.

Usage:
    python manage.py reset_mpesa_number --moderator jp --reason "Left organisation"
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import User, StaffProfile, MpesaResetLog
from notifications.models import Notification


class Command(BaseCommand):
    help = "Reset a moderator's M-Pesa number with a required reason."

    def add_arguments(self, parser):
        parser.add_argument(
            "--moderator",
            required=True,
            help="Username of the moderator whose M-Pesa number should be reset.",
        )
        parser.add_argument(
            "--reason",
            required=True,
            help="Why the reset is being performed (required for audit).",
        )
        parser.add_argument(
            "--reset-by",
            default=None,
            help="Username of the Director performing the reset. "
                 "Defaults to the first active Director account.",
        )

    def handle(self, *args, **options):
        moderator_username = options["moderator"]
        reason = options["reason"].strip()
        reset_by_username = options["reset_by"]

        if not reason:
            raise CommandError("A reason is required.")

        moderator = User.objects.filter(username=moderator_username).first()
        if not moderator:
            raise CommandError(f"Moderator {moderator_username!r} not found.")

        profile = getattr(moderator, "staff_profile", None)
        if not profile:
            raise CommandError(f"{moderator_username} has no staff profile.")

        if reset_by_username:
            reset_by = User.objects.filter(username=reset_by_username).first()
            if not reset_by:
                raise CommandError(f"Reset-by user {reset_by_username!r} not found.")
        else:
            reset_by = User.objects.filter(
                role=User.Role.DIRECTOR, is_active=True,
            ).first()
            if not reset_by:
                raise CommandError("No active Director found; supply --reset-by.")

        previous = profile.mpesa_number or ""

        with transaction.atomic():
            profile.mpesa_number = ""
            profile.save(update_fields=["mpesa_number", "updated_at"])

            MpesaResetLog.objects.create(
                moderator=moderator,
                reset_by=reset_by,
                previous_number=previous,
                reason=reason,
            )

            Notification.objects.create(
                recipient=moderator,
                notification_type=Notification.NotificationType.GENERAL,
                alert_level=Notification.AlertLevel.CRITICAL,
                title="M-Pesa Number Reset",
                message=(
                    "Your M-Pesa number was reset by management. "
                    f"Reason: {reason}. Please enter your correct M-Pesa "
                    "number in your profile (/dashboard/profile/) so "
                    "payments can be processed."
                ),
            )

        self.stdout.write(self.style.SUCCESS(
            f"Reset M-Pesa for {moderator_username}. Previous: {previous!r}. "
            f"Reason: {reason!r}. Logged and moderator notified."
        ))
