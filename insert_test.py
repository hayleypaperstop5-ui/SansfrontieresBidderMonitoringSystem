from pathlib import Path

p = Path("payments/tests.py")
text = p.read_text(encoding="utf-8")

anchor = "    def test_player_chat_rate_method_across_multiple_players(self):"

insert = """    def test_payroll_uses_rate_effective_on_week_end_not_payment_date(self):
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

"""

if anchor not in text:
    raise SystemExit("ERROR: Insertion anchor not found in payments/tests.py")

text = text.replace(anchor, insert + anchor, 1)
p.write_text(text, encoding="utf-8")
print("Successfully inserted test method into payments/tests.py")
