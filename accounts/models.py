from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "System Administrator"
        DIRECTOR = "DIRECTOR", "Director"
        MANAGER = "MANAGER", "Manager"
        MODERATOR = "MODERATOR", "Moderator"
        SUBSTITUTE = "SUBSTITUTE", "Substitute"
        BIDDER = "BIDDER", "Bidder"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.BIDDER,
    )

    def __str__(self):
        return (
            f"{self.get_full_name() or self.username} "
            f"({self.get_role_display()})"
        )


class StaffProfile(models.Model):

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        SUSPENDED = "SUSPENDED", "Suspended"
        DORMANT = "DORMANT", "Dormant"
        TERMINATED = "TERMINATED", "Terminated"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="staff_profile",
    )

    phone_number = models.CharField(
        max_length=30,
        blank=True,
    )

    employee_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    joined_date = models.DateField(
        null=True,
        blank=True,
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

    last_chat_submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    suspension_start = models.DateTimeField(
        null=True,
        blank=True,
    )

    suspension_end = models.DateTimeField(
        null=True,
        blank=True,
    )

    suspension_reason = models.TextField(
        blank=True,
    )

    def save(self, *args, **kwargs):

        is_new = self.pk is None

        super().save(*args, **kwargs)

        if is_new and not self.employee_number:
            self.employee_number = f"SF{self.pk:04d}"

            super().save(
                update_fields=["employee_number"]
            )

    def __str__(self):
        return (
            f"{self.user.get_full_name() or self.user.username} "
            f"({self.get_role_display()})"
        )










