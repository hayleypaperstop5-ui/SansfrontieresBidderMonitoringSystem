from pathlib import Path

path = Path("run_phase1.py")
text = path.read_text(encoding="utf-8-sig")

old = '''routes = [
    "payments:payment_settings",
    "players:chat_rate_list",
    "players:chat_rate_create",
    "players:chat_rate_edit",
    "players:player_chat_rate_list",
    "players:player_chat_rate_create",
    "players:player_chat_rate_edit",
]

for route in routes:
    print(f"{route} -> {reverse(route)}")
'''

new = '''routes = [
    ("payments:payment_settings", {}),
    ("players:chat_rate_list", {}),
    ("players:chat_rate_create", {}),
    ("players:chat_rate_edit", {"rate_id": 1}),
    ("players:player_chat_rate_list", {}),
    ("players:player_chat_rate_create", {"rate_id": 1}),
    ("players:player_chat_rate_edit", {"rate_id": 1}),
]

for route, kwargs in routes:
    print(f"{route} -> {reverse(route, kwargs=kwargs)}")
'''

if old not in text:
    raise RuntimeError("Could not safely locate the URL verification block.")

path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("[SAVED] run_phase1.py updated successfully.")
