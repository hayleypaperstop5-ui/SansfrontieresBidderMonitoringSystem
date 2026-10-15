from pathlib import Path

p = Path("payments/services.py")
b = p.read_bytes()
bom = b.startswith(b"\xef\xbb\xbf")
s = b.decode("utf-8-sig")

marker = (
    "    with transaction.atomic():\n"
    "\n"
    "        qualifying = process_qualifying_player_chats(\n"
)

assert marker in s, "TARGET MARKER NOT FOUND"

replacement = (
    "    with transaction.atomic():\n"
    "\n"
    "        existing_payroll = (\n"
    "            ModeratorPayment.objects\n"
    "            .select_for_update()\n"
    "            .filter(\n"
    "                payment_week_start=week_start,\n"
    "                payment_week_end=week_end,\n"
    "            )\n"
    "            .exists()\n"
    "        )\n"
    "\n"
    "        if existing_payroll:\n"
    "            raise ValidationError(\n"
    "                (\n"
    "                    \"Moderator payroll has already been processed for \"\n"
    "                    f\"{week_start} to {week_end}.\"\n"
    "                )\n"
    "            )\n"
    "\n"
    "        qualifying = process_qualifying_player_chats(\n"
)

s = s.replace(marker, replacement, 1)

p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + s.encode("utf-8"))

print("UPDATED:", p)
print("BOM_PRESERVED:", bom)
print(
    "DUPLICATE_GUARD_ADDED:",
    "existing_payroll = (" in s
    and 'Moderator payroll has already been processed for ' in s,
)
