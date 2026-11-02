"""Create new configuration safely; never overwrite an existing .env."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parent
target = root / '.env'
text = (root / '.env.example').read_text()
for name in ['OAUTH_SIGNING_KEY', 'PANGOLIN_ORIGIN_SECRET']:
    text = text.replace(name+'=\n', name+'='+secrets.token_urlsafe(48)+'\n')
try:
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env already exists. Nothing changed.')
with os.fdopen(fd, 'w') as stream:
    stream.write(text)
print('Created .env with local secrets. Fill Homebox key and OAuth settings locally.')
