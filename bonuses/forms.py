from django import forms

from .models import ChatBonusTier


class ChatBonusTierForm(forms.ModelForm):
    class Meta:
        model = ChatBonusTier
        fields = ("minimum_chats", "bonus_amount", "active", "effective_from")
        widgets = {
            "minimum_chats": forms.NumberInput(attrs={
                "class": "form-input",
                "min": "1",
                "step": "1",
                "placeholder": "e.g. 500",
            }),
            "bonus_amount": forms.NumberInput(attrs={
                "class": "form-input",
                "min": "0.01",
                "step": "0.01",
                "placeholder": "e.g. 250.00",
            }),
            "effective_from": forms.DateInput(attrs={
                "class": "form-input",
                "type": "date",
            }),
            "active": forms.CheckboxInput(attrs={
                "class": "active-checkbox",
            }),
        }
        labels = {
            "minimum_chats": "Chats Required for Bonus",
            "bonus_amount": "Bonus Amount (KES)",
            "effective_from": "Effective From",
        }
        help_texts = {
            "minimum_chats": "Enter the number of chats a Moderator must complete within 24 hours to qualify.",
            "bonus_amount": "Enter the bonus amount paid when the Moderator reaches the required number of chats within 24 hours.",
            "effective_from": "Leave blank for immediate/general applicability.",
        }

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.maximum_chats = None
        instance.qualifying_window_hours = 24

        if commit:
            instance.save()

        return instance
