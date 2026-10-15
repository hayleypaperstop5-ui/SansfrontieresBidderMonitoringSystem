from datetime import date

from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.test import TestCase

from accounts.models import User
from coverage.models import CoverageSession
from players.models import ChatRateTier, Player, PlayerChatRateTier

from .models import (
    ModeratorPayment,
    PaymentRecord,
    PaymentSettings,
    PlayerPayrollLedger,
)
from .services import (
    calculate_gross_amount,
    create_payment_record,
    get_applicable_player_chat_rate_tier,
    get_applicable_rate_tier,
    process_qualifying_player_chats,
    process_thursday_payroll,
)


class PaymentCalculationTests(TestCase):

    def test_flat_rate_calculation(self):
        amount = calculate_gross_amount(400, "3.00")

        self.assertEqual(amount, 1200)


class ApplicableRateTierTests(TestCase):

    def test_selects_correct_chat_volume_tier(self):
        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=300,
            rate_per_chat="2.00",
            active=True,
        )

        high_volume_tier = ChatRateTier.objects.create(
            minimum_chats=301,
            maximum_chats=None,
            rate_per_chat="3.00",
            active=True,
        )

        tier = get_applicable_rate_tier(
            chats_responded=400,
            operating_date=date(2026, 9, 12),
        )

        self.assertEqual(tier, high_volume_tier)

    def test_selects_rate_based_on_effective_date(self):
        old_tier = ChatRateTier.objects.create(
            minimum_chats=301,
            maximum_chats=None,
            rate_per_chat="2.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        new_tier = ChatRateTier.objects.create(
            minimum_chats=301,
            maximum_chats=None,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 9, 1),
        )

        old_rate = get_applicable_rate_tier(
            chats_responded=400,
            operating_date=date(2026, 8, 31),
        )

        new_rate = get_applicable_rate_tier(
            chats_responded=400,
            operating_date=date(2026, 9, 12),
        )

        self.assertEqual(old_rate, old_tier)
        self.assertEqual(new_rate, new_tier)


class PaymentRecordCreationTests(TestCase):

    def setUp(self):
        self.moderator = User.objects.create_user(
            username="payment_test_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player = Player.objects.create(
            player_number=999,
            name="Payment Test Player",
        )

        self.rate_tier = ChatRateTier.objects.create(
            minimum_chats=301,
            maximum_chats=None,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        self.session = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator,
            operating_date=date(2026, 9, 12),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

    def test_creates_payment_record_as_chat_ledger(self):
        payment = create_payment_record(
            coverage_session=self.session,
            chats_responded=400,
        )

        self.assertEqual(payment.chats_responded, 400)
        self.assertEqual(payment.payroll_processed_chats, 0)

    def test_prevents_duplicate_payment_record(self):
        create_payment_record(
            coverage_session=self.session,
            chats_responded=400,
        )

        with self.assertRaises(ValidationError):
            create_payment_record(
                coverage_session=self.session,
                chats_responded=400,
            )

from decimal import Decimal
from unittest.mock import patch

from django.urls import reverse


class PlayerQualificationPayrollTests(TestCase):

    def setUp(self):
        self.moderator_one = User.objects.create_user(
            username="qualification_moderator_one",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.moderator_two = User.objects.create_user(
            username="qualification_moderator_two",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player = Player.objects.create(
            player_number=700,
            name="Qualification Test Player",
        )


    def test_player_qualifies_across_moderators_but_payable_chats_stay_separate(self):
        session_one = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator_one,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        session_two = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator_two,
            operating_date=date(2026, 9, 15),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        record_one = create_payment_record(
            coverage_session=session_one,
            chats_responded=400,
        )

        record_two = create_payment_record(
            coverage_session=session_two,
            chats_responded=300,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
            threshold=700,
        )

        self.assertEqual(
            result["processed_players"][self.player.id]["total_chats"],
            700,
        )
        self.assertEqual(
            result["moderator_totals"][self.moderator_one.id],
            400,
        )
        self.assertEqual(
            result["moderator_totals"][self.moderator_two.id],
            300,
        )

        record_one.refresh_from_db()
        record_two.refresh_from_db()

        self.assertEqual(record_one.payroll_processed_chats, 400)
        self.assertEqual(record_two.payroll_processed_chats, 300)

    def test_player_chats_carry_forward_until_threshold_is_reached(self):
        session_one = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator_one,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        record_one = create_payment_record(
            coverage_session=session_one,
            chats_responded=400,
        )

        first_result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 14),
            threshold=700,
        )

        self.assertNotIn(
            self.player.id,
            first_result["processed_players"],
        )

        record_one.refresh_from_db()
        self.assertEqual(record_one.payroll_processed_chats, 0)

        session_two = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator_two,
            operating_date=date(2026, 9, 21),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        record_two = create_payment_record(
            coverage_session=session_two,
            chats_responded=300,
        )

        second_result = process_qualifying_player_chats(
            week_start=date(2026, 9, 21),
            week_end=date(2026, 9, 27),
            threshold=700,
        )

        self.assertEqual(
            second_result["processed_players"][self.player.id]["total_chats"],
            700,
        )
        self.assertEqual(
            second_result["moderator_totals"][self.moderator_one.id],
            400,
        )
        self.assertEqual(
            second_result["moderator_totals"][self.moderator_two.id],
            300,
        )

        record_one.refresh_from_db()
        record_two.refresh_from_db()

        self.assertEqual(record_one.payroll_processed_chats, 400)
        self.assertEqual(record_two.payroll_processed_chats, 300)


class AnyDayWeeklyPayrollTests(TestCase):

    def setUp(self):
        self.moderator = User.objects.create_user(
            username="anyday_payroll_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player = Player.objects.create(
            player_number=800,
            name="Any Day Payroll Player",
        )

        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="5.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

    def test_weekly_payroll_can_be_processed_on_monday(self):
        session = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        payment_record = create_payment_record(
            coverage_session=session,
            chats_responded=700,
        )

        from .services import process_thursday_payroll

        result = process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
        )

        payment_record.refresh_from_db()

        self.assertEqual(result["week_start"], date(2026, 9, 14))
        self.assertEqual(result["week_end"], date(2026, 9, 20))
        self.assertEqual(payment.payment_date, date(2026, 9, 21))
        self.assertEqual(payment.payable_chats, 700)
        self.assertEqual(payment.chat_earnings, Decimal("3850.00"))
        self.assertEqual(payment.earned_amount, Decimal("3850.00"))
        self.assertEqual(payment_record.payroll_processed_chats, 700)

    def test_duplicate_weekly_payroll_is_rejected_and_ledger_is_unchanged(self):
        session = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        payment_record = create_payment_record(
            coverage_session=session,
            chats_responded=700,
        )

        first_result = process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        self.assertEqual(first_result["payments_created"], 1)
        payment_record.refresh_from_db()
        self.assertEqual(payment_record.payroll_processed_chats, 700)

        with self.assertRaises(ValidationError):
            process_thursday_payroll(
                payment_date=date(2026, 9, 21),
            )

        payment_record.refresh_from_db()
        self.assertEqual(payment_record.payroll_processed_chats, 700)
        self.assertEqual(
            ModeratorPayment.objects.filter(
                moderator=self.moderator,
                payment_week_start=date(2026, 9, 14),
                payment_week_end=date(2026, 9, 20),
            ).count(),
            1,
        )




    def test_review_processing_player_balance_mismatch_rolls_back(self):
        from . import services as payment_services

        session = CoverageSession.objects.create(
            player=self.player,
            moderator=self.moderator,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        payment_record = create_payment_record(
            coverage_session=session,
            chats_responded=700,
        )

        real_build_payroll_plan = payment_services.build_payroll_plan

        def build_plan_then_change_balance(*args, **kwargs):
            reviewed_plan = real_build_payroll_plan(*args, **kwargs)
            payment_record.chats_responded = 701
            payment_record.save(
                update_fields=["chats_responded", "updated_at"]
            )
            return reviewed_plan

        with patch(
            "payments.services.build_payroll_plan",
            side_effect=build_plan_then_change_balance,
        ):
            with self.assertRaisesRegex(
                ValidationError,
                "Payroll changed between review calculation and processing",
            ):
                process_thursday_payroll(
                    payment_date=date(2026, 9, 21),
                )

        payment_record.refresh_from_db()

        self.assertEqual(payment_record.chats_responded, 700)
        self.assertEqual(payment_record.payroll_processed_chats, 0)
        self.assertEqual(PlayerPayrollLedger.objects.count(), 0)
        self.assertEqual(ModeratorPayment.objects.count(), 0)

class ModeratorRateMethodPayrollTests(TestCase):

    def setUp(self):
        self.moderator = User.objects.create_user(
            username="rate_method_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.other_moderator = User.objects.create_user(
            username="other_rate_method_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player_one = Player.objects.create(
            player_number=900,
            name="Rate Method Player One",
        )

        self.player_two = Player.objects.create(
            player_number=901,
            name="Rate Method Player Two",
        )

        self.player_three = Player.objects.create(
            player_number=902,
            name="Below Threshold Player",
        )

        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="5.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat="1.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_one,
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="2.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_two,
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat="1.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_two,
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_three,
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat="2.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player_three,
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="4.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

    def _create_multi_player_payment_records(self):
        scenarios = [
            (self.player_one, self.moderator, 400, date(2026, 9, 14)),
            (self.player_one, self.other_moderator, 500, date(2026, 9, 14)),
            (self.player_two, self.moderator, 250, date(2026, 9, 15)),
            (self.player_two, self.other_moderator, 500, date(2026, 9, 15)),
            (self.player_three, self.moderator, 300, date(2026, 9, 16)),
            (self.player_three, self.other_moderator, 200, date(2026, 9, 16)),
        ]

        records = []

        for player, moderator, chats, operating_date in scenarios:
            session = CoverageSession.objects.create(
                player=player,
                moderator=moderator,
                operating_date=operating_date,
                session_type=CoverageSession.SessionType.DAY,
                status=CoverageSession.Status.COMPLETED,
            )

            records.append(
                create_payment_record(
                    coverage_session=session,
                    chats_responded=chats,
                )
            )

        return records

    def test_chat_tier_rate_method_across_multiple_players(self):
        self._create_multi_player_payment_records()

        PaymentSettings.objects.create(
            moderator_rate_method=ModeratorPayment.RateMethod.CHAT_TIER,
            moderator_payment_method=(
                PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT
            ),
        )

        process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
        )

        self.assertEqual(
            payment.rate_method,
            ModeratorPayment.RateMethod.CHAT_TIER,
        )
        self.assertEqual(payment.chat_tier_rate, Decimal("5.50"))
        self.assertEqual(payment.rate_per_chat, Decimal("5.50"))
        self.assertEqual(payment.payable_chats, 650)
        self.assertEqual(payment.chat_earnings, Decimal("3575.00"))
        self.assertEqual(payment.earned_amount, Decimal("3575.00"))
        self.assertEqual(payment.player_chat_rate_breakdown, {})

    def test_payroll_uses_rate_effective_on_week_end_not_payment_date(self):
        session = CoverageSession.objects.create(
            player=self.player_one,
            moderator=self.moderator,
            operating_date=date(2026, 9, 14),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        create_payment_record(
            coverage_session=session,
            chats_responded=700,
        )

        ChatRateTier.objects.create(
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="9.00",
            active=True,
            effective_from=date(2026, 9, 21),
        )

        PaymentSettings.objects.create(
            moderator_rate_method=ModeratorPayment.RateMethod.CHAT_TIER,
            moderator_payment_method=(
                PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT
            ),
        )

        process_thursday_payroll(
            payment_date=date(2026, 9, 24),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
        )

        self.assertEqual(payment.payment_week_start, date(2026, 9, 14))
        self.assertEqual(payment.payment_week_end, date(2026, 9, 20))
        self.assertEqual(payment.payment_date, date(2026, 9, 24))
        self.assertEqual(payment.chat_tier_rate, Decimal("5.50"))
        self.assertEqual(payment.rate_per_chat, Decimal("5.50"))
        self.assertEqual(payment.payable_chats, 700)
        self.assertEqual(payment.chat_earnings, Decimal("3850.00"))
        self.assertEqual(payment.earned_amount, Decimal("3850.00"))

    def test_player_chat_rate_method_across_multiple_players(self):
        self._create_multi_player_payment_records()

        PaymentSettings.objects.create(
            moderator_rate_method=ModeratorPayment.RateMethod.PLAYER_CHAT_RATE,
            moderator_payment_method=(
                PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT
            ),
        )

        process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
        )

        self.assertEqual(
            payment.rate_method,
            ModeratorPayment.RateMethod.PLAYER_CHAT_RATE,
        )
        self.assertEqual(payment.chat_tier_rate, Decimal("0.00"))
        self.assertEqual(payment.rate_per_chat, Decimal("0.00"))
        self.assertEqual(payment.payable_chats, 650)
        self.assertEqual(
            payment.player_chat_rate_breakdown,
            {
                str(self.player_one.id): {
                    "qualifying_chats": 400,
                    "rate_per_chat": "2.00",
                    "chat_earnings": "800.00",
                },
                str(self.player_two.id): {
                    "qualifying_chats": 250,
                    "rate_per_chat": "3.00",
                    "chat_earnings": "750.00",
                },
            },
        )
        self.assertEqual(payment.chat_earnings, Decimal("1550.00"))
        self.assertEqual(payment.earned_amount, Decimal("1550.00"))

    def test_both_rate_method_across_multiple_players(self):
        self._create_multi_player_payment_records()

        PaymentSettings.objects.create(
            moderator_rate_method=ModeratorPayment.RateMethod.BOTH,
            moderator_payment_method=(
                PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT
            ),
        )

        process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
        )

        self.assertEqual(
            payment.rate_method,
            ModeratorPayment.RateMethod.BOTH,
        )
        self.assertEqual(payment.chat_tier_rate, Decimal("5.50"))
        self.assertEqual(payment.rate_per_chat, Decimal("5.50"))
        self.assertEqual(payment.payable_chats, 650)
        self.assertEqual(
            payment.player_chat_rate_breakdown,
            {
                str(self.player_one.id): {
                    "qualifying_chats": 400,
                    "rate_per_chat": "2.00",
                    "chat_earnings": "4400.00",
                },
                str(self.player_two.id): {
                    "qualifying_chats": 250,
                    "rate_per_chat": "3.00",
                    "chat_earnings": "4125.00",
                },
            },
        )
        self.assertEqual(payment.chat_earnings, Decimal("8525.00"))
        self.assertEqual(payment.earned_amount, Decimal("8525.00"))

        player_three_record = PaymentRecord.objects.get(
            coverage_session__player=self.player_three,
            moderator=self.moderator,
        )

        self.assertEqual(
            player_three_record.payroll_processed_chats,
            0,
        )



class PaymentHistoryViewTests(TestCase):

    def setUp(self):
        self.moderator = User.objects.create_user(
            username="history_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.other_moderator = User.objects.create_user(
            username="other_history_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player_one = Player.objects.create(
            player_number=1001,
            name="History Player One",
        )

        self.player_two = Player.objects.create(
            player_number=1002,
            name="History Player Two",
        )

        self.session_one = CoverageSession.objects.create(
            player=self.player_one,
            moderator=self.moderator,
            operating_date=date(2026, 9, 10),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        self.session_two = CoverageSession.objects.create(
            player=self.player_two,
            moderator=self.moderator,
            operating_date=date(2026, 9, 11),
            session_type=CoverageSession.SessionType.NIGHT,
            status=CoverageSession.Status.COMPLETED,
        )

        PaymentRecord.objects.create(
            moderator=self.moderator,
            coverage_session=self.session_one,
            chats_responded=400,
        )

        PaymentRecord.objects.create(
            moderator=self.moderator,
            coverage_session=self.session_two,
            chats_responded=200,
            payroll_processed_chats=200,
        )
        ModeratorPayment.objects.create(
            moderator=self.moderator,
            payment_week_start=date(2026, 9, 7),
            payment_week_end=date(2026, 9, 13),
            payment_date=date(2026, 9, 17),
            payment_method=ModeratorPayment.PaymentMethod.WEEKLY_PER_CHAT,
            payable_chats=400,
            payroll_processed_chats=400,
            rate_per_chat=Decimal(3.00),
            generated_amount=Decimal(1200.00),
            chat_earnings=Decimal(1200.00),
            bonus_earned=Decimal(400.00),
            monthly_base_amount=Decimal(0.00),
            earned_amount=Decimal(1600.00),
            carried_forward=Decimal(0.00),
            amount_paid=Decimal(400.00),
            outstanding_amount=Decimal(1200.00),
            status=ModeratorPayment.Status.PARTIALLY_PAID,
        )

        other_session = CoverageSession.objects.create(
            player=Player.objects.create(
                player_number=1003,
                name="Other Moderator Player",
            ),
            moderator=self.other_moderator,
            operating_date=date(2026, 9, 12),
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        PaymentRecord.objects.create(
            moderator=self.other_moderator,
            coverage_session=other_session,
            chats_responded=500,
        )

    @patch("payments.views.render", return_value=HttpResponse(status=200))
    def test_moderator_can_view_own_payment_history(self, mock_render):
        self.client.login(
            username="history_moderator",
            password="testpass123",
        )

        response = self.client.get(
            reverse("payments:history"),
        )

        self.assertEqual(response.status_code, 200)
        mock_render.assert_called_once()

        context = mock_render.call_args.args[2]

        self.assertEqual(context["total_chats"], 600)
        self.assertEqual(context["gross_earnings"], Decimal("1600.00"))
        self.assertEqual(context["amount_paid"], Decimal("400.00"))
        self.assertEqual(
            context["outstanding_amount"],
            Decimal("1200.00"),
        )
        self.assertEqual(context["unpaid_count"], 0)
        self.assertEqual(context["paid_count"], 0)

        payment_records = list(context["payment_records"])

        self.assertEqual(len(payment_records), 2)

        self.assertTrue(
            all(
                payment.moderator == self.moderator
                for payment in payment_records
            )
        

        )
    @patch("payments.views.render", return_value=HttpResponse(status=200))
    def test_non_moderator_does_not_receive_payment_records(
        self,
        mock_render,
    ):
        User.objects.create_user(
            username="payment_history_manager",
            password="testpass123",
            role=User.Role.MANAGER,
        )

        self.client.login(
            username="payment_history_manager",
            password="testpass123",
        )

        response = self.client.get(
            reverse("payments:history"),
        )

        self.assertEqual(response.status_code, 200)
        mock_render.assert_called_once()

        context = mock_render.call_args.args[2]

        self.assertEqual(context["payment_records"], [])
        self.assertEqual(context["total_chats"], 0)
        self.assertEqual(context["gross_earnings"], 0)
        self.assertEqual(context["amount_paid"], 0)
        self.assertEqual(context["outstanding_amount"], 0)
        self.assertEqual(context["unpaid_count"], 0)
        self.assertEqual(context["paid_count"], 0)

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(
            reverse("payments:history"),
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)















class PlayerPayrollLedgerPhase2Tests(TestCase):
    def setUp(self):
        self.moderator_one = User.objects.create_user(
            username="phase2_moderator_one",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.moderator_two = User.objects.create_user(
            username="phase2_moderator_two",
            password="testpass123",
            role=User.Role.MODERATOR,
        )

        self.player_one = Player.objects.create(
            player_number=1101,
            name="Phase 2 Ledger Player One",
        )

        self.player_two = Player.objects.create(
            player_number=1102,
            name="Phase 2 Ledger Player Two",
        )

        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=299,
            rate_per_chat="3.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=300,
            maximum_chats=399,
            rate_per_chat="4.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=400,
            maximum_chats=599,
            rate_per_chat="5.00",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat="5.50",
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PaymentSettings.objects.create(
            minimum_chats_per_player=700,
            moderator_rate_method=(
                ModeratorPayment.RateMethod.CHAT_TIER
            ),
            moderator_payment_method=(
                PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT
            ),
        )

    def _create_record(
        self,
        player,
        moderator,
        operating_date,
        chats,
    ):
        session = CoverageSession.objects.create(
            player=player,
            moderator=moderator,
            operating_date=operating_date,
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        return create_payment_record(
            coverage_session=session,
            chats_responded=chats,
        )

    def test_player_below_threshold_remains_unpaid_and_audited(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            500,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(result["processed_players"], {})

        record = PaymentRecord.objects.get(
            moderator=self.moderator_one,
        )

        self.assertEqual(
            record.payroll_processed_chats,
            0,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player_one,
        )

        self.assertEqual(
            ledger.opening_carried_forward,
            0,
        )
        self.assertEqual(
            ledger.current_period_chats,
            500,
        )
        self.assertEqual(
            ledger.total_available_chats,
            500,
        )
        self.assertEqual(
            ledger.qualified_chats,
            0,
        )
        self.assertEqual(
            ledger.processed_chats,
            0,
        )
        self.assertEqual(
            ledger.closing_carried_forward,
            500,
        )
        self.assertEqual(
            ledger.chats_remaining_to_qualification,
            200,
        )

    def test_player_reaching_exactly_700_is_fully_processed(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            700,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            result["moderator_totals"][
                self.moderator_one.id
            ],
            700,
        )

        record = PaymentRecord.objects.get(
            moderator=self.moderator_one,
        )

        self.assertEqual(
            record.payroll_processed_chats,
            700,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player_one,
        )

        self.assertEqual(ledger.total_available_chats, 700)
        self.assertEqual(ledger.qualified_chats, 700)
        self.assertEqual(ledger.processed_chats, 700)
        self.assertEqual(ledger.closing_carried_forward, 0)
        self.assertEqual(
            ledger.chats_remaining_to_qualification,
            0,
        )

    def test_player_exceeding_700_processes_all_unpaid_chats(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            800,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            result["moderator_totals"][
                self.moderator_one.id
            ],
            800,
        )

        record = PaymentRecord.objects.get(
            moderator=self.moderator_one,
        )

        self.assertEqual(
            record.payroll_processed_chats,
            800,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player_one,
        )

        self.assertEqual(ledger.total_available_chats, 800)
        self.assertEqual(ledger.qualified_chats, 800)
        self.assertEqual(ledger.processed_chats, 800)
        self.assertEqual(ledger.closing_carried_forward, 0)

    def test_player_qualifies_across_moderators_without_combining_payable_credit(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            400,
        )

        self._create_record(
            self.player_one,
            self.moderator_two,
            date(2026, 9, 15),
            300,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            result["moderator_totals"][
                self.moderator_one.id
            ],
            400,
        )

        self.assertEqual(
            result["moderator_totals"][
                self.moderator_two.id
            ],
            300,
        )

        self.assertEqual(
            result["moderator_player_totals"][
                self.moderator_one.id
            ][self.player_one.id],
            400,
        )

        self.assertEqual(
            result["moderator_player_totals"][
                self.moderator_two.id
            ][self.player_one.id],
            300,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player_one,
        )

        self.assertEqual(ledger.total_available_chats, 700)
        self.assertEqual(ledger.processed_chats, 700)

    def test_one_moderator_multiple_players_do_not_combine(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            400,
        )

        self._create_record(
            self.player_two,
            self.moderator_one,
            date(2026, 9, 15),
            300,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            result["processed_players"],
            {},
        )

        records = PaymentRecord.objects.filter(
            moderator=self.moderator_one,
        )

        self.assertEqual(
            records.filter(
                payroll_processed_chats=0,
            ).count(),
            2,
        )

        ledger_one = PlayerPayrollLedger.objects.get(
            player=self.player_one,
        )

        ledger_two = PlayerPayrollLedger.objects.get(
            player=self.player_two,
        )

        self.assertEqual(
            ledger_one.total_available_chats,
            400,
        )
        self.assertEqual(
            ledger_two.total_available_chats,
            300,
        )
        self.assertEqual(
            ledger_one.processed_chats,
            0,
        )
        self.assertEqual(
            ledger_two.processed_chats,
            0,
        )

    def test_carry_forward_across_several_periods(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            300,
        )

        first = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(first["processed_players"], {})

        self._create_record(
            self.player_one,
            self.moderator_two,
            date(2026, 9, 21),
            200,
        )

        second = process_qualifying_player_chats(
            week_start=date(2026, 9, 21),
            week_end=date(2026, 9, 27),
        )

        self.assertEqual(second["processed_players"], {})

        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 28),
            200,
        )

        third = process_qualifying_player_chats(
            week_start=date(2026, 9, 28),
            week_end=date(2026, 10, 4),
        )

        self.assertEqual(
            third["moderator_totals"][
                self.moderator_one.id
            ],
            500,
        )

        self.assertEqual(
            third["moderator_totals"][
                self.moderator_two.id
            ],
            200,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player_one,
            payment_week_start=date(2026, 9, 28),
            payment_week_end=date(2026, 10, 4),
        )

        self.assertEqual(
            ledger.opening_carried_forward,
            500,
        )
        self.assertEqual(
            ledger.current_period_chats,
            200,
        )
        self.assertEqual(
            ledger.total_available_chats,
            700,
        )
        self.assertEqual(
            ledger.qualified_chats,
            700,
        )
        self.assertEqual(
            ledger.processed_chats,
            700,
        )
        self.assertEqual(
            ledger.closing_carried_forward,
            0,
        )

    def test_processed_chats_cannot_be_processed_again(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            700,
        )

        first = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            first["moderator_totals"][
                self.moderator_one.id
            ],
            700,
        )

        second = process_qualifying_player_chats(
            week_start=date(2026, 9, 21),
            week_end=date(2026, 9, 27),
        )

        self.assertEqual(
            second["processed_players"],
            {},
        )

        self.assertEqual(
            PaymentRecord.objects.get(
                moderator=self.moderator_one,
            ).payroll_processed_chats,
            700,
        )

    def test_different_players_cannot_combine_to_reach_threshold(self):
        self._create_record(
            self.player_one,
            self.moderator_one,
            date(2026, 9, 14),
            350,
        )

        self._create_record(
            self.player_two,
            self.moderator_two,
            date(2026, 9, 14),
            350,
        )

        result = process_qualifying_player_chats(
            week_start=date(2026, 9, 14),
            week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            result["processed_players"],
            {},
        )

        for moderator in (
            self.moderator_one,
            self.moderator_two,
        ):
            record = PaymentRecord.objects.get(
                moderator=moderator,
            )

            self.assertEqual(
                record.payroll_processed_chats,
                0,
            )

class BonusPayrollIntegrationTests(TestCase):
    def setUp(self):
        from django.utils import timezone
        from accounts.models import StaffProfile, User
        from bonuses.models import ChatBonusTier
        from players.models import ChatRateTier, Player, PlayerChatRateTier

        self.moderator = User.objects.create_user(
            username="bonus_payroll_moderator",
            password="testpass123",
            role=User.Role.MODERATOR,
            first_name="Bonus",
            last_name="Payroll",
        )

        StaffProfile.objects.create(
            user=self.moderator,
            status=StaffProfile.Status.ACTIVE,
        )

        self.player = Player.objects.create(
            player_number=990,
            name="Bonus Payroll Player",
            status=Player.Status.ACTIVE,
        )

        ChatRateTier.objects.create(
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat=Decimal("3.00"),
            active=True,
            effective_from=date(2026, 1, 1),
        )

        ChatRateTier.objects.create(
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat=Decimal("5.50"),
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player,
            minimum_chats=0,
            maximum_chats=599,
            rate_per_chat=Decimal("1.00"),
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PlayerChatRateTier.objects.create(
            player=self.player,
            minimum_chats=600,
            maximum_chats=None,
            rate_per_chat=Decimal("2.00"),
            active=True,
            effective_from=date(2026, 1, 1),
        )

        PaymentSettings.objects.create(
            moderator_rate_method=ModeratorPayment.RateMethod.BOTH,
            minimum_chats_per_player=700,
            payment_day=3,
            moderator_payment_method=PaymentSettings.ModeratorPaymentMethod.WEEKLY_PER_CHAT,
            moderator_monthly_amount=Decimal("0.00"),
        )

        self.bonus_tier = ChatBonusTier.objects.create(
            minimum_chats=500,
            maximum_chats=699,
            bonus_amount=Decimal("200.00"),
            qualifying_window_hours=24,
            active=True,
            effective_from=date(2026, 9, 14),
        )

    def test_real_bonus_award_flows_into_payroll_payment(self):
        from datetime import datetime
        from django.utils import timezone
        from coverage.models import CoverageSession, EndOfSessionReport
        from coverage.services import start_coverage_session
        from bonuses.models import BonusAward
        from bonuses.services import award_bonus_for_report
        from payments.services import (
            build_payroll_plan,
            create_payment_record,
            process_thursday_payroll,
        )
        from payments.models import (
            ModeratorPayment,
            PaymentRecord,
            PaymentSettings,
            PlayerPayrollLedger,
        )

        operating_date = date(2026, 9, 14)
        submitted_at = timezone.make_aware(
            datetime(2026, 9, 14, 12, 0, 0)
        )

        session = start_coverage_session(
            moderator=self.moderator,
            player=self.player,
            moment=submitted_at,
        )

        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = submitted_at
        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "updated_at",
            ]
        )

        report = EndOfSessionReport.objects.create(
            coverage_session=session,
            moderator=self.moderator,
            player=self.player,
            chats_responded=500,
            account_rating=Decimal("8.50"),
            comments="Bonus payroll integration test.",
        )

        EndOfSessionReport.objects.filter(pk=report.pk).update(
            submitted_at=submitted_at,
        )
        report.refresh_from_db()

        award = award_bonus_for_report(
            report=report,
            bonus_date=operating_date,
        )

        self.assertIsNotNone(award)
        self.assertEqual(
            award.bonus_amount,
            Decimal("200.00"),
        )
        self.assertEqual(
            award.moderator_id,
            self.moderator.id,
        )

        create_payment_record(
            coverage_session=session,
            chats_responded=500,
        )

        second_session = CoverageSession.objects.create(
            moderator=self.moderator,
            player=self.player,
            operating_date=operating_date,
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.COMPLETED,
        )

        create_payment_record(
            coverage_session=second_session,
            chats_responded=200,
        )

        plan = build_payroll_plan(
            payment_date=date(2026, 9, 21),
        )

        financial = plan["moderator_financials"][self.moderator.id]

        self.assertEqual(
            financial["payable_chats"],
            700,
        )
        self.assertEqual(
            financial["chat_earnings"],
            Decimal("7700.00"),
        )
        self.assertEqual(
            financial["bonus_earned"],
            Decimal("200.00"),
        )
        self.assertEqual(
            financial["earned_amount"],
            Decimal("7900.00"),
        )

        result = process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        self.assertEqual(
            result["total_payable_chats"],
            700,
        )
        self.assertEqual(
            result["total_chat_earnings"],
            Decimal("7700.00"),
        )
        self.assertEqual(
            result["total_bonuses"],
            Decimal("200.00"),
        )
        self.assertEqual(
            result["total_earned"],
            Decimal("7900.00"),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
            payment_week_start=date(2026, 9, 14),
            payment_week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            payment.bonus_earned,
            Decimal("200.00"),
        )
        self.assertEqual(
            payment.chat_earnings,
            Decimal("7700.00"),
        )
        self.assertEqual(
            payment.earned_amount,
            Decimal("7900.00"),
        )
        self.assertEqual(
            payment.outstanding_amount,
            Decimal("7900.00"),
        )
        self.assertEqual(
            payment.amount_paid,
            Decimal("0.00"),
        )
        self.assertEqual(
            payment.status,
            ModeratorPayment.Status.UNPAID,
        )
        self.assertEqual(
            payment.payroll_processed_chats,
            700,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player,
            payment_week_start=date(2026, 9, 14),
            payment_week_end=date(2026, 9, 20),
        )

        self.assertEqual(ledger.total_available_chats, 700)
        self.assertEqual(ledger.qualified_chats, 700)
        self.assertEqual(ledger.processed_chats, 700)
        self.assertEqual(ledger.closing_carried_forward, 0)

        processed_records = list(PaymentRecord.objects.filter(coverage_session__player=self.player).order_by('id'))
        processed_total = sum(record.payroll_processed_chats for record in processed_records)
        self.assertEqual(processed_total, 700)
        self.assertEqual([record.payroll_processed_chats for record in processed_records], [500, 200])

        self.assertEqual(
            BonusAward.objects.filter(
                moderator=self.moderator,
                bonus_amount=Decimal("200.00"),
            ).count(),
            1,
        )
    def test_bonus_is_paid_while_unqualified_chats_carry_forward(self):
        from datetime import datetime
        from django.utils import timezone
        from coverage.models import CoverageSession, EndOfSessionReport
        from coverage.services import start_coverage_session
        from bonuses.models import BonusAward
        from bonuses.services import award_bonus_for_report
        from payments.services import (
            build_payroll_plan,
            create_payment_record,
            process_thursday_payroll,
        )
        from payments.models import (
            ModeratorPayment,
            PaymentRecord,
            PlayerPayrollLedger,
        )

        operating_date = date(2026, 9, 14)
        submitted_at = timezone.make_aware(
            datetime(2026, 9, 14, 12, 0, 0)
        )

        session = start_coverage_session(
            moderator=self.moderator,
            player=self.player,
            moment=submitted_at,
        )

        session.status = CoverageSession.Status.AWAITING_REPORT
        session.signed_out_at = submitted_at
        session.save(
            update_fields=[
                "status",
                "signed_out_at",
                "updated_at",
            ]
        )

        report = EndOfSessionReport.objects.create(
            coverage_session=session,
            moderator=self.moderator,
            player=self.player,
            chats_responded=500,
            account_rating=Decimal("8.50"),
            comments="Bonus carry-forward integration test.",
        )

        EndOfSessionReport.objects.filter(pk=report.pk).update(
            submitted_at=submitted_at,
        )
        report.refresh_from_db()

        award = award_bonus_for_report(
            report=report,
            bonus_date=operating_date,
        )

        self.assertIsNotNone(award)
        self.assertEqual(
            award.bonus_amount,
            Decimal("200.00"),
        )

        create_payment_record(
            coverage_session=session,
            chats_responded=500,
        )

        plan = build_payroll_plan(
            payment_date=date(2026, 9, 21),
        )

        financial = plan["moderator_financials"][self.moderator.id]

        self.assertEqual(
            financial["payable_chats"],
            0,
        )
        self.assertEqual(
            financial["chat_earnings"],
            Decimal("0.00"),
        )
        self.assertEqual(
            financial["bonus_earned"],
            Decimal("200.00"),
        )
        self.assertEqual(
            financial["earned_amount"],
            Decimal("200.00"),
        )

        result = process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        self.assertEqual(
            result["total_payable_chats"],
            0,
        )
        self.assertEqual(
            result["total_chat_earnings"],
            Decimal("0.00"),
        )
        self.assertEqual(
            result["total_bonuses"],
            Decimal("200.00"),
        )
        self.assertEqual(
            result["total_earned"],
            Decimal("200.00"),
        )

        payment = ModeratorPayment.objects.get(
            moderator=self.moderator,
            payment_week_start=date(2026, 9, 14),
            payment_week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            payment.bonus_earned,
            Decimal("200.00"),
        )
        self.assertEqual(
            payment.chat_earnings,
            Decimal("0.00"),
        )
        self.assertEqual(
            payment.earned_amount,
            Decimal("200.00"),
        )
        self.assertEqual(
            payment.outstanding_amount,
            Decimal("200.00"),
        )
        self.assertEqual(
            payment.payroll_processed_chats,
            0,
        )
        self.assertEqual(
            payment.status,
            ModeratorPayment.Status.UNPAID,
        )

        ledger = PlayerPayrollLedger.objects.get(
            player=self.player,
            payment_week_start=date(2026, 9, 14),
            payment_week_end=date(2026, 9, 20),
        )

        self.assertEqual(
            ledger.total_available_chats,
            500,
        )
        self.assertEqual(
            ledger.qualified_chats,
            0,
        )
        self.assertEqual(
            ledger.processed_chats,
            0,
        )
        self.assertEqual(
            ledger.closing_carried_forward,
            500,
        )
        self.assertEqual(
            ledger.chats_remaining_to_qualification,
            200,
        )

        record = PaymentRecord.objects.get(
            coverage_session=session,
        )

        self.assertEqual(
            record.payroll_processed_chats,
            0,
        )
        self.assertEqual(
            record.chats_responded,
            500,
        )

        self.assertEqual(
            BonusAward.objects.filter(
                moderator=self.moderator,
                bonus_amount=Decimal("200.00"),
            ).count(),
            1,
        )

    def test_late_report_excluded_from_daily_bonus_but_included_in_weekly_payroll(self):
        from datetime import datetime
        from django.utils import timezone
        from bonuses.models import BonusAward
        from bonuses.services import determine_daily_moderator_bonuses
        from coverage.models import CoverageSession, EndOfSessionReport
        from coverage.services import start_coverage_session
        from payments.services import create_payment_record, process_thursday_payroll

        operating_date = date(2026, 9, 14)
        cutoff = timezone.make_aware(
            datetime(2026, 9, 14, 9, 45, 0),
        )
        before_cutoff = timezone.make_aware(
            datetime(2026, 9, 14, 9, 44, 59),
        )
        after_cutoff = timezone.make_aware(
            datetime(2026, 9, 14, 9, 45, 1),
        )

        first_session = start_coverage_session(
            moderator=self.moderator,
            player=self.player,
            moment=before_cutoff,
        )
        first_session.status = CoverageSession.Status.AWAITING_REPORT
        first_session.signed_out_at = before_cutoff
        first_session.save(
            update_fields=["status", "signed_out_at", "updated_at"],
        )
        first_report = EndOfSessionReport.objects.create(
            coverage_session=first_session,
            moderator=self.moderator,
            player=self.player,
            chats_responded=200,
            account_rating=Decimal("8.50"),
            comments="On-time bonus cutoff regression test.",
        )
        EndOfSessionReport.objects.filter(pk=first_report.pk).update(
            submitted_at=before_cutoff,
        )
        first_report.refresh_from_db()
        create_payment_record(
            coverage_session=first_session,
            chats_responded=200,
        )

        late_session = CoverageSession.objects.create(
            moderator=self.moderator,
            player=self.player,
            operating_date=operating_date,
            session_type=CoverageSession.SessionType.DAY,
            status=CoverageSession.Status.AWAITING_REPORT,
            signed_out_at=after_cutoff,
        )
        late_report = EndOfSessionReport.objects.create(
            coverage_session=late_session,
            moderator=self.moderator,
            player=self.player,
            chats_responded=500,
            account_rating=Decimal("8.50"),
            comments="Late report payroll regression test.",
        )
        EndOfSessionReport.objects.filter(pk=late_report.pk).update(
            submitted_at=after_cutoff,
        )
        late_report.refresh_from_db()
        late_payment_record = create_payment_record(
            coverage_session=late_session,
            chats_responded=500,
        )

        awards = determine_daily_moderator_bonuses(
            determination_date=operating_date,
        )

        self.assertEqual(awards, [])
        self.assertEqual(BonusAward.objects.count(), 0)
        self.assertEqual(first_report.submitted_at, before_cutoff)
        self.assertEqual(late_report.submitted_at, after_cutoff)
        self.assertEqual(late_report.chats_responded, 500)
        self.assertEqual(
            EndOfSessionReport.objects.filter(pk=late_report.pk).count(),
            1,
        )
        self.assertEqual(late_payment_record.chats_responded, 500)
        self.assertEqual(late_payment_record.payroll_processed_chats, 0)

        result = process_thursday_payroll(
            payment_date=date(2026, 9, 21),
        )

        self.assertEqual(result["total_payable_chats"], 700)
        self.assertEqual(result["total_chat_earnings"], Decimal("7700.00"))
        self.assertEqual(result["total_bonuses"], Decimal("0.00"))

        late_payment_record.refresh_from_db()
        self.assertEqual(late_payment_record.payroll_processed_chats, 500)
        self.assertEqual(
            PaymentRecord.objects.get(coverage_session=first_session).payroll_processed_chats,
            200,
        )