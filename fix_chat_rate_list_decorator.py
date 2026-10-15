from pathlib import Path

path = Path("players/views.py")

if not path.exists():
    raise FileNotFoundError(f"Could not find required file at {path.resolve()}")

content = path.read_text(encoding="utf-8")

target_def = "def chat_rate_list("
decorator = "@role_required(*RATE_MANAGEMENT_ROLES)"

if target_def not in content:
    raise RuntimeError("Could not locate 'def chat_rate_list(' in players/views.py.")

# Split lines to inspect the decorator context precisely
lines = content.splitlines()
updated_lines = []
modified = False

for i, line in enumerate(lines):
    if line.strip().startswith(target_def):
        # Check preceding lines to see if decorator is already present
        prev_lines = [l.strip() for l in lines[max(0, i-3):i]]
        if any(decorator in l for l in prev_lines):
            print("[OK] Director-only protection is already present on chat_rate_list.")
            updated_lines.append(line)
            continue
        
        # Add decorator prior to function definition
        indent = line[:len(line) - len(line.lstrip())]
        updated_lines.append(f"{indent}{decorator}")
        updated_lines.append(line)
        modified = True
    else:
        updated_lines.append(line)

if modified:
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")
    print("[SAVED] Added Director-only protection to chat_rate_list in players/views.py.")
