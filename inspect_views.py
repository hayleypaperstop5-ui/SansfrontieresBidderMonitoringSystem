from pathlib import Path
import re

p = Path("players/views.py")

if not p.exists():
    print("ERROR: players/views.py does not exist.")
    exit(1)

t = p.read_text(encoding="utf-8")

print("RATE decorator count:", len(re.findall(r'@role_required\(\*RATE_MANAGEMENT_ROLES\)', t)))

m = re.search(r'(?m)(?:@role_required\(\*RATE_MANAGEMENT_ROLES\)\s*)+(?=def player_chat_rate_list)', t)
print("Decorators immediately before player_chat_rate_list:", repr(m.group(0)) if m else "NONE")

lines = t.splitlines()
matches = [i for i, x in enumerate(lines) if x.strip().startswith("def player_chat_rate_list")]

if matches:
    start = matches[0]
    print("\n===== CONTEXT =====")
    print("\n".join(lines[max(0, start - 5):start + 3]))
else:
    print("\n'def player_chat_rate_list' function definition not found in file.")

print("\n===== INTEGRITY =====")
print("UTF-8 BOM:", p.read_bytes().startswith(b'\xef\xbb\xbf'))
print("Backtick-r-n artifacts:", "`r`n" in t)
print("Mojibake Â·:", "Â·" in t)
