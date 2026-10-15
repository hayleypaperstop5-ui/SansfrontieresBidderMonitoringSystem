from pathlib import Path
import re

path = Path("players/views.py")

if not path.exists():
    raise FileNotFoundError(f"Could not locate file at {path.resolve()}")

text = path.read_text(encoding="utf-8")

# Matches multiple consecutive @role_required(*RATE_MANAGEMENT_ROLES) decorators before player_chat_rate_list
pattern = r'(?m)(@role_required\(\*RATE_MANAGEMENT_ROLES\)\s*[\r\n]+){2,}(?=\s*def player_chat_rate_list)'

if not re.search(pattern, text):
    print("[OK] Duplicate decorator block was not found; file is already clean.")
else:
    updated_text = re.sub(pattern, "@role_required(*RATE_MANAGEMENT_ROLES)\n", text)
    path.write_text(updated_text, encoding="utf-8")
    print("[SAVED] Removed the stray duplicate decorator from player_chat_rate_list.")
