from django import forms

from accounts.models import User
from players.models import Player

from .models import Shift
from .services import has_outstanding_shift_report


class ShiftCreationForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = (
            "date",
            "shift_type",
            "player",
            "primary_moderator",
            "scheduled_start",
            "scheduled_end",
            "notes",
        )

        widgets = {
            "date": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
            "scheduled_start": forms.TimeInput(
                attrs={
                    "type": "time",
                }
            ),
            "scheduled_end": forms.TimeInput(
                attrs={
                    "type": "time",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Optional shift notes...",
                }
            ),
        }

        labels = {
            "date": "Shift Date",
            "shift_type": "Shift Type",
            "player": "Player",
            "primary_moderator": "Primary Moderator",
            "scheduled_start": "Scheduled Start",
            "scheduled_end": "Scheduled End",
            "notes": "Notes",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["player"].queryset = Player.objects.filter(
            status=Player.Status.ACTIVE
        ).order_by("player_number")

        moderators = User.objects.filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        ).order_by("first_name", "last_name")

        eligible_moderators = [
            moderator
            for moderator in moderators
            if not has_outstanding_shift_report(moderator)
        ]

        self.fields["primary_moderator"].queryset = User.objects.filter(
            pk__in=[moderator.pk for moderator in eligible_moderators]
        ).order_by("first_name", "last_name")

    def clean(self):
        cleaned_data = super().clean()

        start = cleaned_data.get("scheduled_start")
        end = cleaned_data.get("scheduled_end")

        if start and end and end <= start:
            raise forms.ValidationError(
                "Scheduled end time must be later than the scheduled start time."
            )

        moderator = cleaned_data.get("primary_moderator")

        if moderator and has_outstanding_shift_report(moderator):
            self.add_error(
                "primary_moderator",
                "This Moderator cannot be assigned a new shift because an outstanding shift report is required.",
            )

        return cleaned_data


class ReplacementModeratorAssignmentForm(forms.ModelForm):
    class Meta:
        model = Shift
        fields = ("substitute",)
        labels = {
            "substitute": "Assign Replacement Moderator",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        replacement_moderators = User.objects.filter(
            role=User.Role.MODERATOR,
            is_active=True,
            staff_profile__status="ACTIVE",
        ).order_by("first_name", "last_name")

        eligible_replacement_moderators = [
            replacement_moderator
            for replacement_moderator in replacement_moderators
            if not has_outstanding_shift_report(replacement_moderator)
        ]

        self.fields["substitute"].queryset = User.objects.filter(
            pk__in=[replacement_moderator.pk for replacement_moderator in eligible_replacement_moderators]
        ).order_by("first_name", "last_name")

        self.fields["substitute"].required = True

    def clean_substitute(self):
        substitute = self.cleaned_data["substitute"]

        if has_outstanding_shift_report(substitute):
            raise forms.ValidationError(
                "This Moderator cannot be assigned as a replacement because an outstanding shift report is required."
            )

        return substitute



