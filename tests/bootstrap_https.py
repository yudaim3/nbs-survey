"""Create test-only credentials offline; the HTTPS app never exposes setup."""
import json
import os
from pathlib import Path
import secrets
import sys

sys.path.insert(0,'/app')
from webapp import create_app, create_admin
import survey

state_path=Path('/test-state/smoke.json')
state_path.parent.mkdir(parents=True,exist_ok=True)
if state_path.exists():
    state=json.loads(state_path.read_text(encoding='utf-8'))
else:
    state={'credentials':{'username':'https-check','password':secrets.token_urlsafe(32)}}
    state_path.write_text(json.dumps(state),encoding='utf-8')
app=create_app()
with app.app_context(),survey.connect() as connection:
    connection.execute('BEGIN IMMEDIATE')
    if not connection.execute('SELECT 1 FROM admin_account').fetchone():
        create_admin(connection,**state['credentials'])
# Docker app runs as 10001; initial bootstrap alone runs as root in an isolated volume.
for path in Path('/data').iterdir():
    if path.is_file(): os.chown(path,10001,10001)
os.chown('/data',10001,10001)
print('PASS: isolated HTTPS test administrator is configured (credentials not printed).')
