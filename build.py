import subprocess
import os
import re
import shutil

# 1. Generate today's dashboard from mlb_ace.py
print("Running mlb_ace.py...")
subprocess.run(["python3", "mlb_ace.py", "--date", "today"], check=True)

# 2. Read generated dashboard
with open('acebot_dashboard.html', 'r') as f:
    dashboard_html = f.read()

# 3. Extract the data cards
slate = re.search(r'<div class="card"><h2>Today\'s Slate & Odds</h2>.*?</div>', dashboard_html, re.DOTALL)
totals = re.search(r'<div class="card"><h2>Recommended Totals</h2>.*?</div>', dashboard_html, re.DOTALL)

injected = (slate.group(0) if slate else '') + (totals.group(0) if totals else '')

# 4. Inject into terminal template
with open('index.html', 'r') as f:
    template = f.read()

template = template.replace('<!-- ACEBOT_DATA_INJECT -->', injected)

# 5. Write to dist/
os.makedirs('dist', exist_ok=True)
with open('dist/index.html', 'w') as f:
    f.write(template)

# 6. Copy any assets
if os.path.exists('assets'):
    shutil.copytree('assets', 'dist/assets', dirs_exist_ok=True)

print("Build complete: dist/index.html ready")
