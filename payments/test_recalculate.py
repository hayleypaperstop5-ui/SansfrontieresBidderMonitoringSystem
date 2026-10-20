from datetime import date
from decimal import Decimal
from django.test import TestCase
from accounts.models import User
from payments.models import ModeratorPayment
from payments.services import recalculate_unpaid_rates


class RecalculateBonusPreservationTest(TestCase):

    def test_bonus_not_dropped_when_recalculated(self):
        """Bonus-only row: earned_amount must be exactly bonus after recalc."""
        mod = User.objects.create_user(
            username="rec_mod", email="rec_mod@example.test",
            password="x", role=User.Role.MODERATOR,
        )
        p = ModeratorPayment.objects.create(
            moderator=mod,
            payment_week_start=date(2026, 9, 8),
            payment_week_end=date(2026, 10, 20),
            payment_date=date(2026, 10, 20),
            payable_chats=0,
            earned_amount=Decimal("150.00"),
            bonus_earned=Decimal("150.00"),
            rate_per_chat=Decimal("0.00"),
            rate_method="PLAYER_CHAT_RATE",
            status="UNPAID",
        )
        result = recalculate_unpaid_rates(moderator=mod, apply=True)
        p.refresh_from_db()
        # Bonus-only: earned must stay at bonus (150), not be zeroed.
        self.assertEqual(p.earned_amount, Decimal("150.00"))
        self.assertEqual(p.outstanding_amount, Decimal("150.00"))
