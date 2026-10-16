from django import forms

from .models import ChatRateTier, Player, PlayerChatRateTier


class PlayerCreationForm(forms.ModelForm):

    login_username = forms.CharField(
        required=False,
        max_length=150,
        label="Player Login Username",
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "placeholder": "Player's external account username",
        }),
    )

    login_password = forms.CharField(
        required=False,
        max_length=200,
        label="Player Login Password",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Player's external account password",
        }, render_value=False),
    )

    login_notes = forms.CharField(
        required=False,
        label="Login Notes (optional)",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "2FA notes, recovery email, or other login context",
        }),
    )

    class Meta:
        model = Player
        fields = (
            "player_number",
            "name",
            "login_username",
            "login_password",
            "login_notes",
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

    def save(self, commit=True):
        player = super().save(commit=False)
        plaintext = self.cleaned_data.get("login_password") or ""
        player.login_password = plaintext
        if commit:
            player.save()
        return player


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
                    "placeholder": "e.g. 50.00",
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
            "rate_per_chat": "Rate Per Chat (KES)",
            "active": "Active Rate",
            "effective_from": "Effective From",
        }

        help_texts = {
            "maximum_chats": "Leave blank for an unlimited upper range.",
            "rate_per_chat": "Enter the amount paid in Kenyan Shillings (KES) for each chat under this tier.",
        }


class PlayerChatRateTierForm(forms.ModelForm):

    class Meta:
        model = PlayerChatRateTier
        fields = (
            "player",
            "minimum_chats",
            "maximum_chats",
            "rate_per_chat",
            "active",
            "effective_from",
        )

        widgets = {
            "player": forms.Select(),
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
                    "placeholder": "e.g. 2.00",
                }
            ),
            "effective_from": forms.DateInput(
                attrs={
                    "type": "date",
                }
            ),
        }

        labels = {
            "player": "Player",
            "minimum_chats": "Minimum Chats",
            "maximum_chats": "Maximum Chats",
            "rate_per_chat": "Rate Per Chat (KES)",
            "active": "Active Rate",
            "effective_from": "Effective From",
        }

        help_texts = {
            "maximum_chats": (
                "Leave blank for an unlimited upper range."
            ),
            "rate_per_chat": (
                "Enter the KES amount paid for each qualifying "
                "chat under this Player rate tier."
            ),
            "effective_from": (
                "The date from which this rate becomes applicable."
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        minimum_chats = cleaned_data.get("minimum_chats")
        maximum_chats = cleaned_data.get("maximum_chats")

        if (
            minimum_chats is not None
            and maximum_chats is not None
            and maximum_chats < minimum_chats
        ):
            raise forms.ValidationError(
                "Maximum chats must be greater than or equal to minimum chats."
            )

        return cleaned_data

class PlayerEditForm(forms.ModelForm):

    login_username = forms.CharField(
        required=False,
        max_length=150,
        label="Player Login Username",
        widget=forms.TextInput(attrs={
            "autocomplete": "off",
            "placeholder": "Player's external account username",
        }),
    )

    login_password = forms.CharField(
        required=False,
        max_length=200,
        label="Player Login Password",
        widget=forms.PasswordInput(attrs={
            "autocomplete": "new-password",
            "placeholder": "Leave blank to keep the current password",
        }, render_value=False),
        help_text="Leave blank to keep the existing password unchanged.",
    )

    login_notes = forms.CharField(
        required=False,
        label="Login Notes (optional)",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "2FA notes, recovery email, or other login context",
        }),
    )

    class Meta:
        model = Player
        fields = (
            "player_number",
            "name",
            "status",
            "login_username",
            "login_password",
            "login_notes",
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
        # Prefill plain-text fields from the existing instance.
        # The password field is intentionally left blank.
        if self.instance and self.instance.pk:
            self.fields["login_username"].initial = self.instance.login_username
            self.fields["login_notes"].initial = self.instance.login_notes

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

    def save(self, commit=True):
        player = super().save(commit=False)
        plaintext = self.cleaned_data.get("login_password") or ""
        # Empty password means "keep the existing one"
        if plaintext:
            player.login_password = plaintext
        if commit:
            player.save()
        return player
