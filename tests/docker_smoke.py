"""HTTP smoke test against the separate Docker test stack, never real answers."""
import http.cookiejar
import io
import json
import os
from pathlib import Path
import secrets
import ssl
import sys
import urllib.request
import uuid
from openpyxl import load_workbook
from fixtures import complete_answers

BASE = os.environ.get('NBS_TEST_BASE_URL','http://app:8765')
STATE = Path(os.environ.get('NBS_TEST_STATE','/test-state/smoke.json'))
cookies = http.cookiejar.CookieJar()
handlers = [urllib.request.HTTPCookieProcessor(cookies)]
if os.environ.get('NBS_TEST_CA'):
    handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=os.environ['NBS_TEST_CA'])))
client = urllib.request.build_opener(*handlers)


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
                               'answers': complete_answers(json.loads(request('/api/schema?survey='+state['survey_id']))['schema']), 'other': {}})
    state['custom_id'] = str(uuid.uuid4())
    state['category'] = 'Docker検証カテゴリー'
    request('/api/admin/categories', {'name': state['category']})
    request('/api/admin/surveys', {'id': state['custom_id'], 'title': 'カテゴリー・設問の検証',
            'start': '2026-11-20', 'category': state['category'], 'schema': {'questions': [
                {'title': '満足度', 'type': 'scale', 'required': True},
                {'title': '感想', 'type': 'text', 'required': False}]}})
    request('/api/responses', {'id': str(uuid.uuid4()), 'survey_id': state['custom_id'],
            'name': 'テスト 太郎', 'answers': {'q1': 5}, 'other': {}})
    state['template_id'] = str(uuid.uuid4())
    template = {'id': state['template_id'], 'name': 'Dockerひな形 '+state['template_id'],
                'schema': {'questions': [{'title': '保存する質問', 'type': 'text', 'required': False}]}}
    request('/api/admin/templates', template)
    template['revision'] = 1
    template['schema']['questions'][0]['title'] = '更新した質問'
    request('/api/admin/templates/update', template)
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
if state.get('custom_id'):
    custom = json.loads(request('/api/admin/data?survey='+state['custom_id']))
    assert custom['event']['category'] == state.get('category', '飲み会') and custom['schema']['version'] == 2
    assert custom['event']['category'] in json.loads(request('/api/categories'))['categories']
    assert custom['summary']['total'] == 1 and custom['summary']['questions']['q1']['average'] == 5
    assert custom['summary']['questions']['q2']['missing'] == 1
    custom_book = load_workbook(io.BytesIO(request('/api/admin/export?survey='+state['custom_id'])))
    assert len(custom_book.sheetnames) == 6
if state.get('template_id'):
    saved = next(t for t in json.loads(request('/api/admin/templates'))['templates'] if t['id']==state['template_id'])
    assert saved['revision'] == 2 and saved['schema']['questions'][0]['title'] == '更新した質問'
print('PASS: Docker HTTP login, response storage, templates, summary, and six-sheet Excel (' + sys.argv[1] + ')')
