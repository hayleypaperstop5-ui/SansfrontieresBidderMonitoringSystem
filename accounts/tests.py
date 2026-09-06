from django.test import TestCase

from .forms import StaffCreationForm, StaffEditForm
from .models import StaffProfile, User


class StaffCreationFormTests(TestCase):

    def test_new_staff_creation_has_no_substitute_role(self):
        form = StaffCreationForm()

        self.assertNotIn("role", form.fields)

    def test_new_staff_creation_requires_core_staff_details(self):
        form = StaffCreationForm(
            data={
                "first_name": "Test",
                "last_name": "Moderator",
                "username": "testmoderator",
                "email": "test@example.com",
                "phone_number": "0700000000",
                "password": "StrongPass123!",
            }
        )

        self.assertTrue(form.is_valid())

    def test_staff_edit_form_allows_moderator(self):
        user = User.objects.create_user(
            username="moderator1",
            password="StrongPass123!",
            role=User.Role.MODERATOR,
        )

        profile = StaffProfile.objects.create(
            user=user,
            phone_number="0700000000",
            status=StaffProfile.Status.ACTIVE,
        )

        form = StaffEditForm(
            user=user,
            staff_profile=profile,
        )

        self.assertIn(
            User.Role.MODERATOR,
            dict(form.fields["role"].choices),
        )

    def test_staff_edit_form_does_not_allow_substitute(self):
        user = User.objects.create_user(
            username="moderator2",
            password="StrongPass123!",
            role=User.Role.MODERATOR,
        )

        profile = StaffProfile.objects.create(
            user=user,
            phone_number="0700000001",
            status=StaffProfile.Status.ACTIVE,
        )

        form = StaffEditForm(
            user=user,
            staff_profile=profile,
        )

        role_choices = dict(form.fields["role"].choices)

        self.assertNotIn(
            User.Role.SUBSTITUTE,
            role_choices,
        )
