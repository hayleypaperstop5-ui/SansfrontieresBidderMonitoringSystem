from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import StaffProfile, User


class StaffCreationForm(forms.Form):

    first_name = forms.CharField(
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
    )

    username = forms.CharField(
        max_length=150,
        required=True,
    )

    email = forms.EmailField(
        required=False,
    )

    phone_number = forms.CharField(
        max_length=30,
        required=True,
    )

    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        required=True,
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        if User.objects.filter(
            username__iexact=username
        ).exists():
            raise forms.ValidationError(
                "A user with this username already exists."
            )

        return username



class StaffInvitationForm(forms.Form):

    first_name = forms.CharField(
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
    )

    email = forms.EmailField(
        required=True,
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "A user with this email address already exists."
            )

        return email
class ModeratorSetupForm(forms.Form):

    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput,
        required=True,
    )

    password_confirm = forms.CharField(
        widget=forms.PasswordInput,
        required=True,
        label="Confirm password",
    )

    phone_number = forms.CharField(
        max_length=30,
        required=True,
    )

    whatsapp_number = forms.CharField(
        max_length=30,
        required=True,
    )

    mpesa_number = forms.CharField(
        max_length=30,
        required=True,
        label="M-Pesa number",
    )


    def clean_mpesa_number(self):
        """Validate M-Pesa format and enforce global uniqueness."""
        import re
        number = (self.cleaned_data.get("mpesa_number") or "").strip()

        # Normalize: strip spaces and dashes
        number = re.sub(r"[\s-]+", "", number)

        # Accept formats: 0XXXXXXXXX (10 digits starting with 0),
        # 254XXXXXXXXX (12 digits starting with 254), or +254XXXXXXXXX
        if number.startswith("+254"):
            number = number[1:]
        if re.fullmatch(r"0[17]\d{8}", number):
            pass  # valid local format
        elif re.fullmatch(r"254[17]\d{8}", number):
            pass  # valid international format
        else:
            raise forms.ValidationError(
                "Enter a valid Kenyan M-Pesa number, e.g. 0712345678 "
                "or 254712345678."
            )

        # Uniqueness — exclude the current user's own profile
        existing = StaffProfile.objects.filter(mpesa_number=number)
        if self.staff_profile is not None:
            existing = existing.exclude(pk=self.staff_profile.pk)
        if existing.exists():
            raise forms.ValidationError(
                "This M-Pesa number is already registered to another "
                "moderator. Please enter your own personal number."
            )

        return number


    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean_username(self):
        username = self.cleaned_data["username"].strip()

        if User.objects.filter(
            username__iexact=username
        ).exists():
            raise forms.ValidationError(
                "A user with this username already exists."
            )

        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            self.add_error(
                "password_confirm",
                "The passwords do not match.",
            )

        return cleaned_data

class StaffEditForm(forms.Form):

    first_name = forms.CharField(
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
    )

    email = forms.EmailField(
        required=False,
    )

    phone_number = forms.CharField(
        max_length=30,
        required=True,
    )

    role = forms.ChoiceField(
        choices=(
            (User.Role.DIRECTOR, "Director"),
            (User.Role.MANAGER, "Manager"),
            (User.Role.MODERATOR, "Moderator"),
        ),
        required=True,
    )

    status = forms.ChoiceField(
        choices=StaffProfile.Status.choices,
        required=True,
    )

    notes = forms.CharField(
        required=False,
        widget=forms.Textarea,
    )

    def __init__(self, *args, user=None, staff_profile=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user
        self.staff_profile = staff_profile

        if user and staff_profile and not self.is_bound:
            self.initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "phone_number": staff_profile.phone_number,
                    "role": user.role,
                    "status": staff_profile.status,
                    "notes": staff_profile.notes,
                }
            )

class StaffSelfProfileForm(forms.Form):

    first_name = forms.CharField(
        max_length=150,
        required=True,
    )

    last_name = forms.CharField(
        max_length=150,
        required=True,
    )

    email = forms.EmailField(
        required=True,
    )

    phone_number = forms.CharField(
        max_length=30,
        required=True,
    )

    whatsapp_number = forms.CharField(
        max_length=30,
        required=True,
    )

    mpesa_number = forms.CharField(
        max_length=30,
        required=True,
        label="M-Pesa number",
    )

    def __init__(self, *args, user=None, staff_profile=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user
        self.staff_profile = staff_profile

        if user and staff_profile and not self.is_bound:
            self.initial.update(
                {
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "phone_number": staff_profile.phone_number,
                    "whatsapp_number": staff_profile.whatsapp_number,
                    "mpesa_number": staff_profile.mpesa_number,
                }
            )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        queryset = User.objects.filter(
            email__iexact=email,
        )

        username_queryset = User.objects.filter(
            username__iexact=email,
        )

        if self.user:
            queryset = queryset.exclude(pk=self.user.pk)
            username_queryset = username_queryset.exclude(pk=self.user.pk)

        if queryset.exists() or username_queryset.exists():
            raise forms.ValidationError(
                "This email address is already in use."
            )

        return email

class StaffSuspensionForm(forms.Form):

    suspension_start = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}
        ),
    )

    suspension_end = forms.DateTimeField(
        required=True,
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"}
        ),
    )

    suspension_reason = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Enter the reason for suspension...",
            }
        ),
    )

    def clean(self):
        cleaned_data = super().clean()

        start = cleaned_data.get("suspension_start")
        end = cleaned_data.get("suspension_end")
        reason = cleaned_data.get("suspension_reason")

        if start and end and end <= start:
            raise forms.ValidationError(
                "Suspension end must be later than the suspension start."
            )

        if reason is not None and not reason.strip():
            raise forms.ValidationError(
                "A suspension reason is required."
            )

        return cleaned_data





