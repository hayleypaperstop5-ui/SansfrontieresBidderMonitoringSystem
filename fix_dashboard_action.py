from pathlib import Path
from datetime import datetime
import shutil
import re

path = Path("templates/dashboard/director_dashboard.html")

if not path.exists():
    raise FileNotFoundError(f"Could not find required template at {path.resolve()}")

# 1. Create timestamped backup
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = path.with_name(f"{path.name}.before-payroll-action-fix_{timestamp}.bak")
shutil.copy2(path, backup_path)
print(f"[BACKUP] {backup_path.name}")

# 2. Read file content
content = path.read_text(encoding="utf-8")

# Target replacement block
replacement = """<a
              href="{% url 'payments:payment_settings' %}"
              class="inline-flex items-center justify-center px-5 py-3 rounded-xl bg-indigo-600 text-white text-sm font-bold hover:bg-indigo-700 transition shadow-sm"
            >
              Configure &amp; Review Payroll
            </a>"""

# Flexible regex pattern matching the form block regardless of exact spaces/quotes
pattern = r'<form\s+method=["\']post["\']\s+action=["\']\{\%\s*url\s+[\'"]dashboard:process_payroll[\'"]\s*\%\}\s*[\'"]>.*?<button[^>]*>\s*Process Weekly Payroll\s*</button>\s*</form>'

new_content, count = re.subn(pattern, replacement, content, flags=re.DOTALL)

if count == 0:
    # Check if the change was already applied previously
    if "payments:payment_settings" in content and "Configure &amp; Review Payroll" in content:
        print("[OK] Dashboard payroll action is already configured to point to Payment Settings.")
    else:
        raise RuntimeError("Target payroll action form was not found in director_dashboard.html.")
else:
    path.write_text(new_content, encoding="utf-8")
    print("[SAVED] Dashboard payroll action successfully updated to link to Payment Settings.")
