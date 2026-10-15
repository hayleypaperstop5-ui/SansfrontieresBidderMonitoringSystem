from datetime import date
from django.db import transaction
from payments.models import PaymentRecord, ModeratorPayment
from payments.services import process_thursday_payroll

with transaction.atomic():
    r4 = PaymentRecord.objects.get(id=4)
    r5 = PaymentRecord.objects.get(id=5)

    r4.chats_responded = 400
    r4.payroll_processed_chats = 400
    r4.save(update_fields=["chats_responded", "payroll_processed_chats"])

    r5.chats_responded = 300
    r5.payroll_processed_chats = 0
    r5.save(update_fields=["chats_responded", "payroll_processed_chats"])

    r6 = PaymentRecord.objects.get(id=5)
    r6.pk = None
    r6.chats_responded = 400
    r6.payroll_processed_chats = 0
    r6.save()

    result = process_thursday_payroll(date(2026, 9, 17))

    records = list(
        PaymentRecord.objects
        .filter(coverage_session__player_id=1)
        .values_list(
            "id",
            "moderator__username",
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
        .values_list(
            "moderator__username",
            "payable_chats",
            "earned_amount",
        )
    )

    print("RESULT:", result)
    print("RECORDS DURING TEST:", records)
    print("PAYMENTS DURING TEST:", payments)

    raise RuntimeError("ROLLBACK_MULTI_WEEK_TEST")
