from django.test import TestCase
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.urls import reverse

from accounts.models import StaffProfile, User
from coverage.models import CoverageSession
from .models import ChatRateTier, Player, PlayerChatRateTier


class PlayerCoverageStatusTests(TestCase):

    def setUp(self):
        self.manager = User.objects.create_user(
            username="player_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )

        StaffProfile.objects.create(
            user=self.manager,
            status=StaffProfile.Status.ACTIVE,
        )

        self.player = Player.objects.create(
            player_number=1,
            name="Player One",
            status=Player.Status.ACTIVE,
        )

        self.client.force_login(self.manager)

    def test_active_player_without_coverage_can_be_deactivated(self):
        response = self.client.post(
            reverse(
                "players:player_deactivate",
                args=[self.player.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        self.player.refresh_from_db()

        self.assertEqual(
            self.player.status,
            Player.Status.INACTIVE,
        )

    def test_player_with_open_coverage_cannot_be_deactivated(self):
        CoverageSession.objects.create(
            player=self.player,
            moderator=User.objects.create_user(
                username="coverage_moderator",
                password="testpass123",
                role=User.Role.MODERATOR,
            ),
            operating_date=self.player.created_at.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.OPEN,
        )

        response = self.client.post(
            reverse(
                "players:player_deactivate",
                args=[self.player.id],
            )
        )

        self.assertEqual(response.status_code, 302)

        self.player.refresh_from_db()

        self.assertEqual(
            self.player.status,
            Player.Status.ACTIVE,
        )


class PlayerChatRateTierTests(TestCase):

    def setUp(self):
        self.player_one = Player.objects.create(
            player_number=1,
            name="Player One",
            status=Player.Status.ACTIVE,
        )

        self.player_two = Player.objects.create(
            player_number=2,
            name="Player Two",
            status=Player.Status.ACTIVE,
        )

    def test_valid_player_chat_rate_tier_can_be_created(self):
        tier = PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        self.assertEqual(tier.player, self.player_one)
        self.assertEqual(tier.rate_per_chat, Decimal("2.00"))

    def test_invalid_chat_range_is_rejected(self):
        tier = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=300,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        with self.assertRaises(ValidationError):
            tier.full_clean()

    def test_overlapping_active_tiers_for_same_player_are_rejected(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        overlapping = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=200,
            maximum_chats=399,
            rate_per_chat="3.00",
        )

        with self.assertRaises(ValidationError):
            overlapping.full_clean()

    def test_same_range_is_allowed_for_different_players(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier = PlayerChatRateTier(
            player=self.player_two,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier.full_clean()

    def test_inactive_overlapping_tier_is_allowed(self):
        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat=Decimal("2.00"),
        )

        tier = PlayerChatRateTier(
            player=self.player_one,
            minimum_chats=200,
            maximum_chats=399,
            rate_per_chat="3.00",
            active=False,
        )

        tier.full_clean()



class PlayerChatRateManagementTests(TestCase):
    """
    Legacy per-player chat rate URLs now redirect to the global rate page.

    The per-player rate model was deprecated and consolidated into a single
    global ChatRateTier card. These tests verify the redirects work for
    anyone with a stale bookmark.
    """

    def setUp(self):
        self.director = User.objects.create_user(
            username="rate_director",
            password="testpass123",
            role=User.Role.DIRECTOR,
        )
        self.moderator = User.objects.create_user(
            username="rate_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

    def test_per_player_chat_rate_list_redirects_to_global(self):
        self.client.force_login(self.director)
        response = self.client.get("/players/player-chat-rates/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/players/chat-rates/")

    def test_per_player_chat_rate_create_redirects_to_global_create(self):
        self.client.force_login(self.director)
        response = self.client.get("/players/player-chat-rates/add/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/players/chat-rates/add/")

    def test_per_player_chat_rate_edit_redirects_to_global_list(self):
        self.client.force_login(self.director)
        response = self.client.get("/players/player-chat-rates/1/edit/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/players/chat-rates/")

    def test_global_chat_rate_list_requires_management_role(self):
        self.client.force_login(self.moderator)
        response = self.client.get("/players/chat-rates/")
        # role_required should reject moderators (redirect away)
        self.assertIn(response.status_code, (302, 403))

class ChatRateTierConstraintTests(TestCase):
    """Verify overlap and range validation on ChatRateTier."""

    def test_inverted_range_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            ChatRateTier.objects.create(
                minimum_chats=300, maximum_chats=100, rate_per_chat=5, active=True,
            )

    def test_overlapping_active_tier_raises_validation_error(self):
        from django.core.exceptions import ValidationError
        ChatRateTier.objects.create(
            minimum_chats=0, maximum_chats=299, rate_per_chat=3, active=True,
        )
        with self.assertRaises(ValidationError):
            ChatRateTier.objects.create(
                minimum_chats=100, maximum_chats=400, rate_per_chat=5, active=True,
            )

    def test_non_overlapping_tiers_save_successfully(self):
        ChatRateTier.objects.create(
            minimum_chats=0, maximum_chats=299, rate_per_chat=3, active=True,
        )
        ChatRateTier.objects.create(
            minimum_chats=300, maximum_chats=599, rate_per_chat=4.5, active=True,
        )
        self.assertEqual(ChatRateTier.objects.count(), 2)

    def test_inactive_tier_can_overlap(self):
        ChatRateTier.objects.create(
            minimum_chats=0, maximum_chats=299, rate_per_chat=3, active=True,
        )
        ChatRateTier.objects.create(
            minimum_chats=100, maximum_chats=200, rate_per_chat=5, active=False,
        )
        self.assertEqual(ChatRateTier.objects.filter(active=False).count(), 1)
