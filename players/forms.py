from django import forms

from .models import ChatRateTier, Player


class PlayerCreationForm(forms.ModelForm):

    class Meta:
        model = Player
        fields = (
            "player_number",
            "name",
        )

        widgets = {
            "player_number": forms.NumberInput(
                attrs={
                    "min": 1,
                    "max": 10,
                    "placeholder": "Enter player number (1-10)",
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter player name",
                }
            ),
        }

        labels = {
            "player_number": "Player Number",
            "name": "Player Name",
        }

    def clean_player_number(self):
        player_number = self.cleaned_data["player_number"]

        if player_number < 1 or player_number > 10:
            raise forms.ValidationError(
                "Player number must be between 1 and 10."
            )

        if Player.objects.filter(
            player_number=player_number
        ).exists():
            raise forms.ValidationError(
                f"Player {player_number} already exists."
            )

        return player_number

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError(
                "Player name is required."
            )

        return name


class ChatRateTierForm(forms.ModelForm):

    class Meta:
        model = ChatRateTier
        fields = (
            "minimum_chats",
            "maximum_chats",
            "rate_per_chat",
            "active",
            "effective_from",
        )

        widgets = {
            "minimum_chats": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "e.g. 0",
                }
            ),
            "maximum_chats": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Leave blank for unlimited",
                }
            ),
            "rate_per_chat": forms.NumberInput(
                attrs={
                    "min": 0,
                    "step": "0.01",
                    "placeholder": "e.g. 0.50",
                }
            ),
            "effective_from": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
        }

        labels = {
            "minimum_chats": "Minimum Chats",
            "maximum_chats": "Maximum Chats",
            "rate_per_chat": "Rate Per Chat",
            "active": "Active Rate",
            "effective_from": "Effective From",
        }

        help_texts = {
            "maximum_chats": "Leave blank for an unlimited upper range.",
            "rate_per_chat": "The amount paid for each chat under this applicable tier.",
        }

class PlayerEditForm(forms.ModelForm):

    class Meta:
        model = Player
        fields = (
            "player_number",
            "name",
            "status",
        )

        widgets = {
            "player_number": forms.NumberInput(
                attrs={
                    "min": 1,
                    "max": 10,
                }
            ),
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Enter player name",
                }
            ),
        }

        labels = {
            "player_number": "Player Number",
            "name": "Player Name",
            "status": "Player Status",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def clean_player_number(self):
        player_number = self.cleaned_data["player_number"]

        if player_number < 1 or player_number > 10:
            raise forms.ValidationError(
                "Player number must be between 1 and 10."
            )

        existing_player = Player.objects.filter(
            player_number=player_number
        ).exclude(pk=self.instance.pk)

        if existing_player.exists():
            raise forms.ValidationError(
                f"Player {player_number} already exists."
            )

        return player_number

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        if not name:
            raise forms.ValidationError(
                "Player name is required."
            )

        return name
