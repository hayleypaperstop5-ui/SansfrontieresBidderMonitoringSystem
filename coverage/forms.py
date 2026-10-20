from django import forms

from .models import EndOfSessionReport


class EndOfSessionReportForm(forms.ModelForm):
    chats_responded = forms.IntegerField(
        required=True,
        min_value=0,
    )

    screenshot = forms.ImageField(
        required=True,
        error_messages={
            "required": "Screenshot / evidence is required to submit this report.",
            "invalid_image": "Please upload a valid image file (JPG, PNG, etc).",
        },
    )

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
            "screenshot": "Upload the screenshot or other evidence from the session. This is required to submit the report.",
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
