from django import forms

from .models import EndOfSessionReport


class EndOfSessionReportForm(forms.ModelForm):
    class Meta:
        model = EndOfSessionReport
        fields = (
            "chats_responded",
            "account_rating",
            "screenshot",
            "comments",
        )
        widgets = {
            "chats_responded": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Enter the number of chats responded to",
                }
            ),
            "account_rating": forms.NumberInput(
                attrs={
                    "min": 0,
                    "max": 10,
                    "step": "0.01",
                    "placeholder": "Enter account rating (0–10)",
                }
            ),
            "screenshot": forms.ClearableFileInput(),
            "comments": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Enter any relevant comments about the session...",
                }
            ),
        }
        labels = {
            "chats_responded": "Number of Chats Responded To",
            "account_rating": "Account Rating",
            "screenshot": "Screenshot / Evidence",
            "comments": "Comments",
        }
        help_texts = {
            "chats_responded": "Enter the total number of chats you responded to during this coverage session.",
            "account_rating": "Enter the player account rating from 0 to 10.",
            "screenshot": "Upload screenshot or other evidence from the session if required.",
            "comments": "Provide any additional information management should know.",
        }


class ContinuationResponseForm(forms.Form):
    response = forms.ChoiceField(
        choices=[
            ("YES", "YES ? Continue covering this Player"),
            ("NO", "NO ? End this coverage session"),
        ],
        widget=forms.RadioSelect,
        required=True,
    )
