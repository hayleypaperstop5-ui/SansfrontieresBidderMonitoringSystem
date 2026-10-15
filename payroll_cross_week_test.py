from datetime import date
from django.db import transaction

from coverage.models import CoverageSession
from payments.models import PaymentRecord, ModeratorPayment
from payments.services import process_thursday_payroll

with transaction.atomic():
    r4 = PaymentRecord.objects.get(id=4)
    r5 = PaymentRecord.objects.get(id=5)

    s4 = r4.coverage_session
    s5 = r5.coverage_session

    # Simulate 400 unpaid chats carried forward from the previous week.
    s4.operating_date = date(2026, 9, 10)
    s4.save(update_fields=["operating_date"])

    r4.chats_responded = 400
    r4.payroll_processed_chats = 0
    r4.save(
        update_fields=[
            "chats_responded",
            "payroll_processed_chats",
        ]
    )

    # Simulate 300 new unpaid chats during the current week.
    s5.operating_date = date(2026, 9, 16)
    s5.save(update_fields=["operating_date"])

    r5.chats_responded = 300
    r5.payroll_processed_chats = 0
    r5.save(
        update_fields=[
            "chats_responded",
            "payroll_processed_chats",
        ]
    )

    result = process_thursday_payroll(
        date(2026, 9, 17)
    )

    records = list(
        PaymentRecord.objects
        .filter(coverage_session__player_id=1)
        .order_by("id")
        .values_list(
            "id",
            "moderator__username",
            "coverage_session__operating_date",
            "chats_responded",
            "payroll_processed_chats",
        )
    )

    payments = list(
        ModeratorPayment.objects
        .filter(
            payment_week_start=date(2026, 9, 14),
            payment_week_end=date(2026, 9, 20),
        )
        .order_by("moderator__username")
        .values_list(
            "moderator__username",
            "payable_chats",
            "rate_per_chat",
            "earned_amount",
        )
    )

    print("RESULT:", result)
    print("RECORDS DURING TEST:", records)
    print("PAYMENTS DURING TEST:", payments)

    raise RuntimeError(
        "ROLLBACK_CROSS_WEEK_CARRY_FORWARD_TEST"
    )
