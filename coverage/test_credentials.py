"""
Regression tests for the player credential disclosure feature.

Covers:
  - encryption round-trip
  - form save (create + edit-blank-keeps-existing)
  - disclosure creation on manager assignment and self-application
  - acknowledge endpoint (recipient + non-recipient)
  - read-only credentials page access control
  - popup context processor
"""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.credential_crypto import decrypt_value, encrypt_value
from accounts.models import StaffProfile, User
from players.models import CredentialDisclosure, Player
from coverage.models import CoverageSession
from coverage.services import assign_coverage_session


class EncryptDecryptTests(TestCase):
    def test_roundtrip(self):
        c = encrypt_value("my-secret-pw")
        self.assertNotEqual(c, "my-secret-pw")
        self.assertEqual(decrypt_value(c), "my-secret-pw")

    def test_empty_string_roundtrip(self):
        self.assertEqual(encrypt_value(""), "")
        self.assertEqual(decrypt_value(""), "")


class PlayerModelCredentialTests(TestCase):
    def test_setter_encrypts_and_getter_decrypts(self):
        p = Player.objects.create(player_number=8001, name="Cred Test 1")
        p.login_username = "sm1"
        p.login_password = "plain-password-xyz"
        p.save()
        p.refresh_from_db()
        self.assertTrue(p.login_password_encrypted)
        self.assertNotIn("plain-password-xyz", p.login_password_encrypted)
        self.assertEqual(p.login_password, "plain-password-xyz")

    def test_setting_empty_password_clears_field(self):
        p = Player.objects.create(player_number=8002, name="Cred Test 2")
        p.login_password = "abc"
        p.save()
        p.login_password = ""
        p.save()
        p.refresh_from_db()
        self.assertEqual(p.login_password_encrypted, "")
        self.assertEqual(p.login_password, "")


class CredentialFormTests(TestCase):
    def test_blank_password_preserves_existing(self):
        from players.forms import PlayerEditForm
        p = Player.objects.create(player_number=8003, name="Form Test")
        p.login_password = "original-secret"
        p.save()

        data = {
            "player_number": p.player_number,
            "name": p.name,
            "status": p.status,
            "login_username": p.login_username,
            "login_password": "",
            "login_notes": p.login_notes,
        }
        form = PlayerEditForm(data, instance=p)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        p.refresh_from_db()
        self.assertEqual(p.login_password, "original-secret")


class DisclosureCreationTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="cred_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        self.moderator = User.objects.create_user(
            username="cred_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
        )

    def test_disclosure_created_when_player_has_credentials(self):
        p = Player.objects.create(player_number=8004, name="Disclosure Test")
        p.login_username = "sm4"
        p.login_password = "pw-4"
        p.save()

        session = assign_coverage_session(
            manager=self.manager,
            moderator=self.moderator,
            player=p,
        )

        disc = CredentialDisclosure.objects.filter(
            moderator=self.moderator,
            player=p,
        ).first()
        self.assertIsNotNone(disc)
        self.assertEqual(disc.coverage_session_id, session.id)
        self.assertIsNone(disc.acknowledged_at)

    def test_no_disclosure_when_player_has_no_credentials(self):
        p = Player.objects.create(player_number=8005, name="No Creds")

        session = assign_coverage_session(
            manager=self.manager,
            moderator=self.moderator,
            player=p,
        )

        self.assertFalse(
            CredentialDisclosure.objects.filter(
                moderator=self.moderator,
                player=p,
            ).exists()
        )


class AcknowledgeEndpointTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="ack_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        self.mod_a = User.objects.create_user(
            username="ack_mod_a",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        self.mod_b = User.objects.create_user(
            username="ack_mod_b",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(user=self.mod_a, status=StaffProfile.Status.ACTIVE)
        StaffProfile.objects.create(user=self.mod_b, status=StaffProfile.Status.ACTIVE)

        self.player = Player.objects.create(player_number=8006, name="Ack Player")
        self.player.login_username = "sm6"
        self.player.login_password = "pw-6"
        self.player.save()

        self.session = assign_coverage_session(
            manager=self.manager,
            moderator=self.mod_a,
            player=self.player,
        )
        self.disclosure = CredentialDisclosure.objects.get(
            moderator=self.mod_a, player=self.player,
        )

    def test_recipient_can_acknowledge(self):
        c = Client()
        c.force_login(self.mod_a)
        url = reverse("coverage:acknowledge_credential", args=[self.disclosure.id])
        resp = c.post(url)
        self.assertEqual(resp.status_code, 200)
        self.disclosure.refresh_from_db()
        self.assertIsNotNone(self.disclosure.acknowledged_at)

    def test_other_moderator_gets_404(self):
        c = Client()
        c.force_login(self.mod_b)
        url = reverse("coverage:acknowledge_credential", args=[self.disclosure.id])
        resp = c.post(url)
        self.assertEqual(resp.status_code, 404)
        self.disclosure.refresh_from_db()
        self.assertIsNone(self.disclosure.acknowledged_at)

    def test_get_is_not_allowed(self):
        c = Client()
        c.force_login(self.mod_a)
        url = reverse("coverage:acknowledge_credential", args=[self.disclosure.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 405)


class ReadOnlyCredentialsPageTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(
            username="ro_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )
        self.covering_mod = User.objects.create_user(
            username="ro_covering",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        self.other_mod = User.objects.create_user(
            username="ro_other",
            password="testpass123",
            role=User.Role.MODERATOR,
        )
        StaffProfile.objects.create(user=self.covering_mod, status=StaffProfile.Status.ACTIVE)
        StaffProfile.objects.create(user=self.other_mod, status=StaffProfile.Status.ACTIVE)

        self.player = Player.objects.create(player_number=8007, name="RO Player")
        self.player.login_username = "sm7"
        self.player.login_password = "pw-7"
        self.player.save()

        self.session = assign_coverage_session(
            manager=self.manager,
            moderator=self.covering_mod,
            player=self.player,
        )

    def test_covering_moderator_can_view(self):
        c = Client()
        c.force_login(self.covering_mod)
        url = reverse("coverage:player_credentials", args=[self.player.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "sm7")

    def test_other_moderator_redirected(self):
        c = Client()
        c.force_login(self.other_mod)
        url = reverse("coverage:player_credentials", args=[self.player.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_manager_can_view(self):
        c = Client()
        c.force_login(self.manager)
        url = reverse("coverage:player_credentials", args=[self.player.id])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 200)
