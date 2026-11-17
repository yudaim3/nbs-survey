"""HTTP smoke test against the separate Docker test stack, never real answers."""
import http.cookiejar
import io
import json
from pathlib import Path
import secrets
import sys
import urllib.request
import uuid
from openpyxl import load_workbook

BASE = 'http://app:8765'
STATE = Path('/test-state/smoke.json')
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def request(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={} if body is None else {'Content-Type': 'application/json', 'Origin': BASE})
    with client.open(req, timeout=60) as response:
        return response.read()


if sys.argv[1] == 'seed':
    if STATE.exists():
        state = json.loads(STATE.read_text())
        request('/api/auth/login', state['credentials'])
    else:
        state = {'credentials': {'username': 'docker-check', 'password': secrets.token_urlsafe(24)}}
        request('/api/auth/setup', state['credentials'])
    state['survey_id'] = str(uuid.uuid4())
    request('/api/admin/surveys', {'id': state['survey_id'], 'title': 'Docker自動検証用', 'start': '2026-11-16', 'end': '', 'place': 'テスト'})
    request('/api/responses', {'id': str(uuid.uuid4()), 'survey_id': state['survey_id'], 'name': 'テスト',
                               'answers': {'q1': '4：満足', 'q3': 'Dockerからのテスト回答'}, 'other': {}})
    STATE.write_text(json.dumps(state), encoding='utf-8')
else:
    state = json.loads(STATE.read_text())
    request('/api/auth/login', state['credentials'])
sid = state['survey_id']
data = json.loads(request('/api/admin/data?survey=' + sid))
assert data['summary']['total'] == 1
assert data['summary']['questions']['q1']['average'] == 4
book = load_workbook(io.BytesIO(request('/api/admin/export?survey=' + sid)))
assert len(book.sheetnames) == 6 and book['集計サマリー']['B8'].value == 1
assert book['集計サマリー']['B9'].value == 4
print('PASS: Docker HTTP login, response storage, summary, and six-sheet Excel (' + sys.argv[1] + ')')
