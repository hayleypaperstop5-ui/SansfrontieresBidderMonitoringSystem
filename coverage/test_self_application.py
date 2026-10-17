from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from accounts.models import StaffProfile
from coverage.models import CoverageApplication, CoverageSession
from coverage.self_application import (
    apply_for_player,
    get_chats_this_week,
    get_coverage_opportunities,
    moderator_is_eligible,
)
from players.models import Player

User = get_user_model()

class SelfApplicationTestDataMixin:
    def make_user(self, username, role="MODERATOR"):
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestPassword123!",
        )
        user.role = role
        user.is_active = True
        user.save()
        StaffProfile.objects.update_or_create(
            user=user,
            defaults={"status": StaffProfile.Status.ACTIVE},
        )
        return user

    def make_player(self, number):
        return Player.objects.create(
            player_number=number,
            status=Player.Status.ACTIVE,
        )

    def make_report_session(self, moderator, player):
        moment = timezone.localtime()
        return CoverageSession.objects.create(
            moderator=moderator,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

class ModeratorEligibilityTests(SelfApplicationTestDataMixin, TestCase):
    def test_eligible_moderator_is_eligible(self):
        moderator = self.make_user("eligible1")
        self.assertTrue(moderator_is_eligible(moderator, timezone.localtime()))

    def test_inactive_user_is_not_eligible(self):
        moderator = self.make_user("inactive1")
        moderator.is_active = False
        moderator.save(update_fields=["is_active"])
        self.assertFalse(moderator_is_eligible(moderator, timezone.localtime()))

    def test_suspended_moderator_is_not_eligible(self):
        moderator = self.make_user("suspended1")
        moderator.staff_profile.status = StaffProfile.Status.SUSPENDED
        moderator.staff_profile.save(update_fields=["status"])
        self.assertFalse(moderator_is_eligible(moderator, timezone.localtime()))

    def test_terminated_moderator_is_not_eligible(self):
        moderator = self.make_user("terminated1")
        moderator.staff_profile.status = StaffProfile.Status.TERMINATED
        moderator.staff_profile.save(update_fields=["status"])
        self.assertFalse(moderator_is_eligible(moderator, timezone.localtime()))

    def test_moderator_with_active_assignment_is_not_eligible(self):
        moderator = self.make_user("busy1")
        player = self.make_player(9001)
        moment = timezone.localtime()
        CoverageSession.objects.create(
            moderator=moderator,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.ACTIVE,
        )
        self.assertFalse(moderator_is_eligible(moderator, moment))

    def test_moderator_with_awaiting_report_is_not_eligible(self):
        moderator = self.make_user("reportpending1")
        player = self.make_player(9002)
        moment = timezone.localtime()
        CoverageSession.objects.create(
            moderator=moderator,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.AWAITING_REPORT,
        )
        self.assertFalse(moderator_is_eligible(moderator, moment))

class CoverageOpportunityTests(SelfApplicationTestDataMixin, TestCase):
    def test_eligible_moderator_sees_active_uncovered_player(self):
        moderator = self.make_user("opportunity1")
        player = self.make_player(9010)
        result = get_coverage_opportunities(moderator, timezone.localtime())
        self.assertTrue(result["eligible"])
        self.assertIn(player, list(result["new_players"]))

    def test_deactivated_player_is_not_an_opportunity(self):
        moderator = self.make_user("opportunity2")
        player = self.make_player(9011)
        player.status = Player.Status.INACTIVE
        player.save(update_fields=["status"])
        result = get_coverage_opportunities(moderator, timezone.localtime())
        self.assertNotIn(player, list(result["new_players"]))

    def test_currently_covered_player_is_not_a_new_opportunity(self):
        moderator = self.make_user("opportunity3")
        player = self.make_player(9012)
        covering_moderator = self.make_user("covering3")
        moment = timezone.localtime()
        CoverageSession.objects.create(
            moderator=covering_moderator,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.ACTIVE,
        )
        result = get_coverage_opportunities(moderator, moment)
        self.assertNotIn(player, list(result["new_players"]))

    def test_replacement_requested_player_is_an_opportunity(self):
        moderator = self.make_user("replacement1")
        outgoing = self.make_user("outgoing1")
        player = self.make_player(9013)
        moment = timezone.localtime()
        CoverageSession.objects.create(
            moderator=outgoing,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.REPLACEMENT_REQUESTED,
            replacement_requested_at=moment,
        )
        result = get_coverage_opportunities(moderator, moment)
        replacement_player_ids = {s.player_id for s in result["replacement_sessions"]}
        self.assertIn(player.id, replacement_player_ids)

class SelfApplicationAwardTests(SelfApplicationTestDataMixin, TestCase):
    @patch("coverage.self_application.get_chats_this_week", return_value=80)
    def test_single_application_records_weekly_chats_and_assigns_player(self, mocked_weekly_chats):
        moderator = self.make_user("single1")
        player = self.make_player(9020)
        winner, session, awarded = apply_for_player(
            moderator, player.id, CoverageApplication.OpportunityType.NEW, timezone.localtime()
        )
        self.assertTrue(awarded)
        self.assertEqual(winner.moderator_id, moderator.id)
        self.assertIsNotNone(session)
        self.assertEqual(session.player_id, player.id)
        application = CoverageApplication.objects.get(moderator=moderator, player=player)
        self.assertEqual(application.chats_this_week, 80)
        self.assertEqual(application.status, CoverageApplication.Status.WON)
        self.assertEqual(application.resulting_session_id, session.id)
        self.assertEqual(CoverageSession.objects.filter(player=player, status=CoverageSession.Status.ACTIVE).count(), 1)

    def test_two_moderators_highest_weekly_chats_wins(self):
        moderator_a = self.make_user("competition_a")
        moderator_b = self.make_user("competition_b")
        player = self.make_player(9030)
        moment = timezone.localtime()

        def weekly_chats_for(user, when=None):
            return {moderator_a.id: 80, moderator_b.id: 150}[user.id]

        with patch("coverage.self_application.get_chats_this_week", side_effect=weekly_chats_for):
            winner_a, session_a, awarded_a = apply_for_player(
                moderator_a, player.id, CoverageApplication.OpportunityType.NEW, moment
            )
        self.assertTrue(awarded_a)
        self.assertEqual(winner_a.moderator_id, moderator_a.id)

        with patch("coverage.self_application.get_chats_this_week", return_value=150):
            with self.assertRaises(ValueError):
                apply_for_player(moderator_b, player.id, CoverageApplication.OpportunityType.NEW, moment)

        self.assertEqual(CoverageSession.objects.filter(player=player, status=CoverageSession.Status.ACTIVE).count(), 1)

    def test_competition_selection_uses_highest_snapshot_when_pending_applications_exist(self):
        moderator_a = self.make_user("pending_a")
        moderator_b = self.make_user("pending_b")
        player = self.make_player(9040)
        now = timezone.localtime()

        application_a = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_a,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=80,
            status=CoverageApplication.Status.PENDING,
        )
        application_b = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_b,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=150,
            status=CoverageApplication.Status.PENDING,
        )

        CoverageApplication.objects.filter(pk=application_a.pk).update(applied_at=now - timedelta(seconds=10))
        CoverageApplication.objects.filter(pk=application_b.pk).update(applied_at=now)

        with patch("coverage.self_application.get_chats_this_week", return_value=150):
            winner, session, awarded = apply_for_player(
                moderator_b, player.id, CoverageApplication.OpportunityType.NEW, now
            )

        self.assertTrue(awarded)
        self.assertEqual(winner.id, application_b.id)
        self.assertEqual(session.player_id, player.id)

        application_a.refresh_from_db()
        application_b.refresh_from_db()

        self.assertEqual(application_b.status, CoverageApplication.Status.WON)
        self.assertEqual(application_a.status, CoverageApplication.Status.LOST)

    def test_equal_weekly_chats_use_earlier_application(self):
        moderator_a = self.make_user("tie_a")
        moderator_b = self.make_user("tie_b")
        player = self.make_player(9050)
        now = timezone.localtime()

        application_a = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_a,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=100,
            status=CoverageApplication.Status.PENDING,
        )
        application_b = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_b,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=100,
            status=CoverageApplication.Status.PENDING,
        )

        CoverageApplication.objects.filter(pk=application_a.pk).update(applied_at=now - timedelta(seconds=10))
        CoverageApplication.objects.filter(pk=application_b.pk).update(applied_at=now)

        with patch("coverage.self_application.get_chats_this_week", return_value=100):
            winner, session, awarded = apply_for_player(
                moderator_b, player.id, CoverageApplication.OpportunityType.NEW, now
            )

        self.assertTrue(awarded)
        self.assertEqual(winner.id, application_a.id)

        application_a.refresh_from_db()
        application_b.refresh_from_db()

        self.assertEqual(application_a.status, CoverageApplication.Status.WON)
        self.assertEqual(application_b.status, CoverageApplication.Status.LOST)

    def test_losing_applicant_is_marked_lost(self):
        moderator_a = self.make_user("loser_a")
        moderator_b = self.make_user("loser_b")
        player = self.make_player(9060)
        now = timezone.localtime()

        application_a = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_a,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=80,
            status=CoverageApplication.Status.PENDING,
            applied_at=now - timedelta(seconds=5),
        )
        application_b = CoverageApplication.objects.create(
            player=player,
            moderator=moderator_b,
            opportunity_type=CoverageApplication.OpportunityType.NEW,
            chats_this_week=150,
            status=CoverageApplication.Status.PENDING,
            applied_at=now,
        )

        with patch("coverage.self_application.get_chats_this_week", return_value=150):
            winner, session, awarded = apply_for_player(
                moderator_b, player.id, CoverageApplication.OpportunityType.NEW, now
            )

        self.assertTrue(awarded)
        application_a.refresh_from_db()
        self.assertEqual(application_a.status, CoverageApplication.Status.LOST)
        self.assertEqual(CoverageApplication.objects.filter(player=player, status=CoverageApplication.Status.WON).count(), 1)

    def test_moderator_cannot_receive_two_players(self):
        moderator = self.make_user("one_player_only")
        player_a = self.make_player(9070)
        player_b = self.make_player(9071)
        now = timezone.localtime()

        with patch("coverage.self_application.get_chats_this_week", return_value=100):
            winner, session, awarded = apply_for_player(
                moderator, player_a.id, CoverageApplication.OpportunityType.NEW, now
            )

        self.assertTrue(awarded)

        with patch("coverage.self_application.get_chats_this_week", return_value=100):
            with self.assertRaises(ValueError):
                apply_for_player(moderator, player_b.id, CoverageApplication.OpportunityType.NEW, now)

        self.assertFalse(CoverageSession.objects.filter(moderator=moderator, player=player_b).exists())

    def test_duplicate_application_is_idempotent(self):
        moderator = self.make_user("duplicate1")
        player = self.make_player(9080)
        now = timezone.localtime()

        with patch("coverage.self_application.get_chats_this_week", return_value=120):
            first_winner, first_session, first_awarded = apply_for_player(
                moderator, player.id, CoverageApplication.OpportunityType.NEW, now
            )

        with patch("coverage.self_application.get_chats_this_week", return_value=120):
            second_winner, second_session, second_awarded = apply_for_player(
                moderator, player.id, CoverageApplication.OpportunityType.NEW, now
            )

        self.assertEqual(first_winner.id, second_winner.id)
        self.assertEqual(first_session.id, second_session.id)
        self.assertTrue(first_awarded)
        self.assertFalse(second_awarded)
        self.assertEqual(CoverageApplication.objects.filter(moderator=moderator, player=player).count(), 1)

class WeeklyChatCalculationTests(SelfApplicationTestDataMixin, TestCase):
    def test_weekly_chat_calculation_uses_current_week(self):
        moderator = self.make_user("weekly1")
        with patch("coverage.models.EndOfSessionReport.objects.filter") as mocked_filter:
            mocked_filter.return_value.aggregate.return_value = {"total": 275}
            total = get_chats_this_week(moderator, timezone.localtime())

        self.assertEqual(total, 275)
        mocked_filter.assert_called_once()

class ReplacementApplicationTests(SelfApplicationTestDataMixin, TestCase):
    def test_replacement_application_assigns_replacement_moderator(self):
        incoming = self.make_user("incoming1")
        outgoing = self.make_user("outgoing2")
        player = self.make_player(9090)
        moment = timezone.localtime()

        replacement_request = CoverageSession.objects.create(
            moderator=outgoing,
            player=player,
            operating_date=moment.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.REPLACEMENT_REQUESTED,
            replacement_requested_at=moment,
        )

        with patch("coverage.self_application.get_chats_this_week", return_value=200):
            winner, new_session, awarded = apply_for_player(
                incoming, player.id, CoverageApplication.OpportunityType.REPLACEMENT, moment
            )

        self.assertTrue(awarded)
        self.assertEqual(winner.moderator_id, incoming.id)
        self.assertEqual(new_session.player_id, player.id)
        self.assertEqual(new_session.moderator_id, incoming.id)

        replacement_request.refresh_from_db()
        self.assertEqual(replacement_request.status, CoverageSession.Status.HANDOVER)
        self.assertEqual(replacement_request.replacement_moderator_id, incoming.id)
        self.assertEqual(replacement_request.replacement_session_id, new_session.id)

class ConcurrentApplicationTests(SelfApplicationTestDataMixin, TransactionTestCase):
    reset_sequences = True

    def test_concurrent_applications_allow_only_one_winner(self):
        if connection.vendor == "sqlite":
            self.skipTest("SQLite does not provide required locking semantics.")

        from concurrent.futures import ThreadPoolExecutor

        moderator_a = self.make_user("race_a")
        moderator_b = self.make_user("race_b")
        player = self.make_player(9100)
        now = timezone.localtime()

        def attempt(moderator, chats):
            from django.db import close_old_connections

            close_old_connections()
            try:
                with patch("coverage.self_application.get_chats_this_week", return_value=chats):
                    result = apply_for_player(
                        moderator, player.id, CoverageApplication.OpportunityType.NEW, now
                    )
                return ("success", result[0].id, result[2])
            except Exception as exc:
                return ("error", type(exc).__name__, str(exc))
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(attempt, moderator_a, 80)
            future_b = executor.submit(attempt, moderator_b, 150)
            result_a = future_a.result()
            result_b = future_b.result()

        results = [result_a, result_b]
        self.assertEqual(CoverageApplication.objects.filter(player=player, status=CoverageApplication.Status.WON).count(), 1)
        self.assertEqual(CoverageSession.objects.filter(player=player, status=CoverageSession.Status.ACTIVE).count(), 1)
        self.assertEqual(CoverageApplication.objects.filter(player=player, status=CoverageApplication.Status.LOST).count(), 1)
        self.assertEqual(sum(r[0] == "success" for r in results), 1)

class ReplacementConsolidationTests(SelfApplicationTestDataMixin, TestCase):
    """Verify _assign_replacement_locked delegates to the canonical service."""

    def test_assign_replacement_locked_delegates_to_service(self):
        from coverage.self_application import _assign_replacement_locked
        from coverage.models import CoverageSession, CoverageApplication
        from coverage.services import assign_replacement
        from unittest.mock import patch

        moderator_a = self.make_user("consol_mod_a")
        moderator_b = self.make_user("consol_mod_b")
        player = self.make_player(9101)
        now = timezone.localtime()

        outgoing = CoverageSession.objects.create(
            moderator=moderator_a,
            player=player,
            operating_date=now.date(),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.ACTIVE,
            signed_in_at=now,
        )

        application = CoverageApplication.objects.create(
            moderator=moderator_b,
            player=player,
            opportunity_type=CoverageApplication.OpportunityType.REPLACEMENT,
            status=CoverageApplication.Status.WON,
            chats_this_week=100,
        )

        with patch(
            "coverage.services.assign_replacement",
            wraps=assign_replacement,
        ) as mocked:
            result = _assign_replacement_locked(application, outgoing, now)
            self.assertTrue(
                mocked.called,
                "_assign_replacement_locked must delegate to assign_replacement",
            )
