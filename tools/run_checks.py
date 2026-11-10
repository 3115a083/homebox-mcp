"""Run isolated regression checks, without accessing a live inventory."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
checks = ['request_limits.py', 'photo_upload.py', 'deletion_guards.py',
          'ferret_proxy.py', 'ferret_tool_parity.py', 'attachment_export.py', 'ferret_migration.py', 'ferret_mcp_transport.py', 'care_setup_checks.py',
          'gateway_smoke.py', 'release_contracts.py']
for check in checks:
    print('CHECK', check, flush=True)
    subprocess.run([sys.executable, str(root / 'tests' / check)], cwd=root, check=True, timeout=120)
print('All isolated checks passed.', flush=True)
