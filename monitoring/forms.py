from django import forms

from .models import ChatSubmission


class ChatSubmissionForm(forms.ModelForm):

    class Meta:
        model = ChatSubmission
        fields = (
            "chat_reference",
            "chat_content",
        )

        widgets = {
            "chat_reference": forms.TextInput(
                attrs={
                    "placeholder": "Enter the chat reference or ID",
                }
            ),
            "chat_content": forms.Textarea(
                attrs={
                    "rows": 10,
                    "placeholder": "Enter the moderated chat content or summary...",
                }
            ),
        }

        labels = {
            "chat_reference": "Chat Reference",
            "chat_content": "Chat Content / Summary",
        }
