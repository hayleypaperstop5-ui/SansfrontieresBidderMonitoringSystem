from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import User, StaffProfile
from notifications.models import Notification
from shifts.models import Shift
from shifts.services import get_report_enforcement_at


class Command(BaseCommand):
    help = "Check shift report deadlines and notify Managers about overdue reports."

    def handle(self, *args, **options):
        now = timezone.now()

        overdue_count = 0
        notification_count = 0

        managers = User.objects.filter(
            role=User.Role.MANAGER,
            is_active=True,
            staff_profile__status=StaffProfile.Status.ACTIVE,
        ).distinct()

        shifts = Shift.objects.select_related(
            "actual_worker",
            "player",
        ).filter(
            status=Shift.Status.AWAITING_REPORT,
            actual_worker__isnull=False,
            report__isnull=True,
        )

        for shift in shifts:
            enforcement_at = get_report_enforcement_at(shift)

            if now >= enforcement_at:
                overdue_count += 1

                shift.status = Shift.Status.REPORT_OVERDUE
                shift.save(update_fields=["status", "updated_at"])

                worker_name = (
                    shift.actual_worker.get_full_name()
                    or shift.actual_worker.username
                )

                self.stdout.write(
                    self.style.WARNING(
                        f"OVERDUE REPORT: {worker_name} | "
                        f"Player {shift.player.player_number} - "
                        f"{shift.player.name} | "
                        f"Shift date {shift.date:%d %b %Y}"
                    )
                )

                for manager in managers:
                    notification, created = Notification.objects.get_or_create(
                        recipient=manager,
                        notification_type=Notification.NotificationType.OVERDUE_SHIFT_REPORT,
                        shift=shift,
                        defaults={
                            "title": "Overdue Shift Report",
                            "message": (
                                f"{worker_name} has not submitted the required "
                                f"End-of-Shift Report for Player "
                                f"{shift.player.player_number} - "
                                f"{shift.player.name} on "
                                f"{shift.date:%d %b %Y}. "
                                f"The worker is blocked from taking further "
                                f"shifts until the report is submitted. "
                                f"Please arrange a substitution or replacement."
                            ),
                        },
                    )

                    if created:
                        notification_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Deadline check completed. "
                f"{overdue_count} overdue shift report(s) found. "
                f"{notification_count} new Manager notification(s) created."
            )
        )
