from pathlib import Path

p = Path("payments/tests.py")
b = p.read_bytes()
bom = b.startswith(b"\xef\xbb\xbf")
s = b.decode("utf-8-sig")
lines = s.splitlines(keepends=True)

assert len(lines) >= 347, f"Unexpected file length: {len(lines)}"
assert lines[343].strip() == 'self.assertEqual(payment_record.payroll_processed_chats, 700)', "Unexpected line 344"
assert lines[346].strip() == "class ModeratorRateMethodPayrollTests(TestCase):", "Unexpected line 347"

addition = [
    "\n",
    "    def test_duplicate_weekly_payroll_is_rejected_and_ledger_is_unchanged(self):\n",
    "        session = CoverageSession.objects.create(\n",
    "            player=self.player,\n",
    "            moderator=self.moderator,\n",
    "            operating_date=date(2026, 9, 14),\n",
    "            session_type=CoverageSession.SessionType.DAY,\n",
    "            status=CoverageSession.Status.COMPLETED,\n",
    "        )\n",
    "\n",
    "        payment_record = create_payment_record(\n",
    "            coverage_session=session,\n",
    "            chats_responded=700,\n",
    "        )\n",
    "\n",
    "        first_result = process_thursday_payroll(\n",
    "            payment_date=date(2026, 9, 21),\n",
    "        )\n",
    "\n",
    "        self.assertEqual(first_result[\"payments_created\"], 1)\n",
    "        payment_record.refresh_from_db()\n",
    "        self.assertEqual(payment_record.payroll_processed_chats, 700)\n",
    "\n",
    "        with self.assertRaises(ValidationError):\n",
    "            process_thursday_payroll(\n",
    "                payment_date=date(2026, 9, 21),\n",
    "            )\n",
    "\n",
    "        payment_record.refresh_from_db()\n",
    "        self.assertEqual(payment_record.payroll_processed_chats, 700)\n",
    "        self.assertEqual(\n",
    "            ModeratorPayment.objects.filter(\n",
    "                moderator=self.moderator,\n",
    "                payment_week_start=date(2026, 9, 14),\n",
    "                payment_week_end=date(2026, 9, 20),\n",
    "            ).count(),\n",
    "            1,\n",
    "        )\n",
    "\n",
]

lines[344:344] = addition
p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + "".join(lines).encode("utf-8"))

print("UPDATED:", p)
print("BOM_PRESERVED:", bom)
print("TEST_ADDED:", any("test_duplicate_weekly_payroll_is_rejected_and_ledger_is_unchanged" in line for line in lines))
