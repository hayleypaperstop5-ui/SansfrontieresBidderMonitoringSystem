from django import forms

from .models import PaymentSettings


class PaymentSettingsForm(forms.ModelForm):
    payment_day = forms.TypedChoiceField(
        choices=[
            (0, "Monday"),
            (1, "Tuesday"),
            (2, "Wednesday"),
            (3, "Thursday"),
            (4, "Friday"),
            (5, "Saturday"),
            (6, "Sunday"),
        ],
        coerce=int,
        label="Payroll Processing Day",
        help_text=(
            "The normal day selected for weekly payroll processing. "
            "Payroll can still be processed manually on another day."
        ),
        widget=forms.Select(attrs={"class": "form-input"}),
    )

    class Meta:
        model = PaymentSettings
        fields = (
            "moderator_rate_method",
            "minimum_chats_per_player",
            "payment_day",
            "moderator_payment_method",
            "moderator_monthly_amount",
        )
        widgets = {
            "moderator_rate_method": forms.Select(attrs={
                "class": "form-input",
            }),
            "minimum_chats_per_player": forms.NumberInput(attrs={
                "class": "form-input",
                "min": "0",
                "step": "1",
                "placeholder": "e.g. 700",
            }),
            "moderator_payment_method": forms.Select(attrs={
                "class": "form-input",
            }),
            "moderator_monthly_amount": forms.NumberInput(attrs={
                "class": "form-input",
                "min": "0",
                "step": "0.01",
                "placeholder": "e.g. 25000.00",
            }),
        }
        labels = {
            "moderator_rate_method": "Moderator Rate Method",
            "minimum_chats_per_player": "Qualification Threshold per Player",
            "moderator_payment_method": "Moderator Payment Method",
            "moderator_monthly_amount": "Monthly Moderator Amount (KES)",
        }
        help_texts = {
            "moderator_rate_method": (
                "Choose whether qualifying chat earnings use the global Chat "
                "Tier rate, each Player's Chat Rate, or both."
            ),
            "minimum_chats_per_player": (
                "A Player must reach this many combined chats from all "
                "Moderators before that Player's chats become payable."
            ),
            "moderator_payment_method": (
                "Choose weekly per-chat earnings or a monthly Moderator "
                "base amount."
            ),
            "moderator_monthly_amount": (
                "Used when the Moderator payment method is Monthly. "
                "Enter the monthly base amount in KES."
            ),
        }

    def clean(self):
        cleaned_data = super().clean()

        payment_method = cleaned_data.get("moderator_payment_method")
        monthly_amount = cleaned_data.get("moderator_monthly_amount")

        if payment_method == PaymentSettings.ModeratorPaymentMethod.MONTHLY:
            if monthly_amount is None or monthly_amount <= 0:
                self.add_error(
                    "moderator_monthly_amount",
                    "Enter a monthly Moderator amount greater than zero.",
                )

        return cleaned_data
