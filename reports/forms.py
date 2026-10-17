from django import forms

from .models import ShiftReport


class ShiftReportForm(forms.ModelForm):
    class Meta:
        model = ShiftReport
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
                    "placeholder": "Enter number of chats responded to",
                }
            ),
            "account_rating": forms.NumberInput(
                attrs={
                    "min": 0,
                    "max": 10,
                    "step": "0.01",
                    "placeholder": "Enter account rating",
                }
            ),
            "screenshot": forms.ClearableFileInput(
                attrs={
                    "accept": ".jpg,.jpeg,.png",
                }
            ),
            "comments": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Optional comments about the shift...",
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
            "chats_responded": "Enter the total number of chats you responded to during this shift.",
            "account_rating": "Enter the account rating at the end of the shift, from 0 to 10.",
            "screenshot": "Upload JPG, JPEG or PNG evidence of the account activity.",
        }
