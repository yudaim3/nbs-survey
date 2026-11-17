"""Portable WSGI application for NBS SURVEY."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
import uuid

from flask import Flask, jsonify, request, make_response, send_file
from werkzeug.exceptions import HTTPException
import survey
from excel_export import export_workbook

ROOT = Path(__file__).resolve().parent


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    if value.lower() not in ('true', 'false', '1', '0'):
        raise ValueError(f'{name} must be true or false')
    return value.lower() in ('true', '1')


def create_admin(connection, username, password):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}', username):
        raise ValueError('管理者IDは半角英数字・_ . @ - を使い、3〜80文字で設定してください。')
    if not 12 <= len(password) <= 128:
        raise ValueError('パスワードは12〜128文字で設定してください。')
    salt = secrets.token_hex(16)
    connection.execute('INSERT INTO admin_account VALUES (1,?,?,?)',
                       (username, salt, survey.password_hash(password, salt)))


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    public_url = os.environ.get('PUBLIC_URL', '').rstrip('/')
    if public_url:
        parsed = urlsplit(public_url)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or
                parsed.password or parsed.path or parsed.query or parsed.fragment):
            raise ValueError('PUBLIC_URL must be an origin, e.g. https://survey.example.com')
    port = int(os.environ.get('PORT', '8765'))
    app.config.update(
        DATABASE=str(Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'survey.sqlite3'),
        PUBLIC_URL=public_url,
        ALLOWED_HOSTS={h.strip().lower() for h in os.environ.get(
            'ALLOWED_HOSTS', f'localhost:{port},127.0.0.1:{port}').split(',') if h.strip()},
        ALLOW_ADMIN_SETUP=env_bool('ALLOW_ADMIN_SETUP', False),
        SECURE_COOKIE=env_bool('SECURE_COOKIE', public_url.startswith('https://')),
        MAX_CONTENT_LENGTH=250000,
    )
    if public_url:
        app.config['ALLOWED_HOSTS'].add(urlsplit(public_url).netloc.lower())
    if config:
        app.config.update(config)
    if '*' in app.config['ALLOWED_HOSTS']:
        raise ValueError('Use explicit ALLOWED_HOSTS; wildcard is not supported')
    if app.config['PUBLIC_URL'] and app.config['ALLOW_ADMIN_SETUP']:
        raise ValueError('Disable ALLOW_ADMIN_SETUP before setting a public URL')
    if app.config['PUBLIC_URL'].startswith('https://') and not app.config['SECURE_COOKIE']:
        raise ValueError('HTTPS requires SECURE_COOKIE=true')
    with app.app_context():
        survey.initialize()

    def error(message, status):
        return jsonify(error=message), status

    def session_hash():
        token = request.cookies.get('awaji_admin', '')
        return hashlib.sha256(token.encode()).hexdigest() if token else ''

    def authenticated():
        with survey.connect() as c:
            return c.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>?',
                             (session_hash(), time.time())).fetchone() is not None

    def set_cookie(response, token, age=28800):
        response.set_cookie('awaji_admin', token, max_age=age, httponly=True,
                            secure=app.config['SECURE_COOKIE'], samesite='Strict', path='/')
        return response

    @app.before_request
    def check_request():
        if request.host.lower() not in app.config['ALLOWED_HOSTS']:
            return error('このホストからのアクセスは許可されていません。', 403)
        if request.method == 'POST':
            expected = app.config['PUBLIC_URL'] or f'http://{request.host}'
            if request.headers.get('Origin') and request.headers['Origin'] != expected:
                return error('送信元が一致しません。', 403)
            if request.mimetype != 'application/json':
                return error('JSON形式が必要です。', 415)
        if request.path.startswith('/api/admin/') and not authenticated():
            return error('管理者ログインが必要です。', 401)

    @app.after_request
    def security_headers(response):
        response.headers.update({
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
            'Content-Security-Policy': "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        })
        return response

    @app.errorhandler(HTTPException)
    def http_error(exc):
        messages = {400: '入力形式が正しくありません。', 404: 'ページが見つかりません。',
                    405: 'この操作は許可されていません。', 413: '送信サイズが上限を超えています。'}
        return error(messages.get(exc.code, 'リクエストを処理できませんでした。'), exc.code)

    @app.errorhandler(ValueError)
    @app.errorhandler(TypeError)
    def invalid_input(exc):
        return error(str(exc), 400)

    @app.errorhandler(LookupError)
    def not_found(exc):
        return error(str(exc), 404)

    @app.errorhandler(sqlite3.Error)
    def database_error(exc):
        app.logger.exception('Database operation failed')
        return error('データを処理できませんでした。時間をおいて再度お試しください。', 500)

    @app.get('/api/health')
    def health():
        with survey.connect() as c:
            c.execute('SELECT 1').fetchone()
        return jsonify(ok=True, app='nbs-workation')

    @app.get('/api/auth/state')
    def auth_state():
        with survey.connect() as c:
            configured = c.execute('SELECT 1 FROM admin_account').fetchone() is not None
        return jsonify(configured=configured, authenticated=authenticated(), setup_allowed=app.config['ALLOW_ADMIN_SETUP'])

    @app.post('/api/auth/<action>')
    def auth(action):
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('入力形式が正しくありません。')
        if action == 'logout':
            with survey.connect() as c:
                c.execute('DELETE FROM sessions WHERE token_hash=?', (session_hash(),))
            return set_cookie(make_response(jsonify(ok=True)), '', 0)
        if action not in ('setup', 'login'):
            return error('APIが見つかりません。', 404)
        username, password = body.get('username', ''), body.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str) or len(username) > 80 or len(password) > 128:
            raise ValueError('IDまたはパスワードの形式が正しくありません。')
        username = username.strip()
        # Use the socket peer; never trust an arbitrary X-Forwarded-For header.
        client = request.remote_addr or 'unknown'
        with survey.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            account = c.execute('SELECT * FROM admin_account WHERE id=1').fetchone()
            if action == 'setup':
                if account:
                    return error('管理者は設定済みです。ログインしてください。', 409)
                if not app.config['ALLOW_ADMIN_SETUP']:
                    return error('初回設定はサーバー管理者が行ってください。', 403)
                create_admin(c, username, password)
            else:
                attempt = c.execute('SELECT * FROM auth_attempts WHERE client=?', (client,)).fetchone()
                if attempt and attempt['reset_at'] > time.time() and attempt['attempts'] >= 5:
                    return error('ログイン失敗が続いたため、15分ほど待ってからお試しください。', 429)
                candidate = survey.password_hash(password, account['salt'] if account else '0' * 32)
                if not account or not (hmac.compare_digest(account['username'].encode(), username.encode()) &
                                       hmac.compare_digest(account['password_hash'], candidate)):
                    active = attempt and attempt['reset_at'] > time.time()
                    count = attempt['attempts'] + 1 if active else 1
                    reset = attempt['reset_at'] if active else time.time() + 900
                    c.execute('INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)', (client, count, reset))
                    return error('管理者IDまたはパスワードが正しくありません。', 401)
                c.execute('DELETE FROM auth_attempts WHERE client=?', (client,))
            token = secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires_at<=? OR token_hash=?', (time.time(), session_hash()))
            c.execute('INSERT INTO sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(), time.time() + 28800))
        return set_cookie(make_response(jsonify(ok=True)), token)

    @app.get('/api/surveys')
    @app.get('/api/admin/surveys')
    def surveys():
        items = survey.list_surveys(admin=request.path.startswith('/api/admin/'))
        category = request.args.get('category')
        if category: items = [s for s in items if s['event']['category'] == category]
        return jsonify(surveys=items, categories=survey.list_categories())

    @app.get('/api/categories')
    def categories():
        return jsonify(categories=survey.list_categories())

    @app.post('/api/admin/categories')
    def add_category():
        body = request.get_json()
        if not isinstance(body, dict): raise ValueError('入力形式が正しくありません。')
        name, created = survey.add_category(body.get('name'))
        return jsonify(name=name, created=created, categories=survey.list_categories()), 201 if created else 200

    @app.get('/api/admin/template')
    def template():
        return jsonify(schema=survey.SCHEMA)

    @app.get('/api/admin/templates')
    def templates():
        return jsonify(templates=survey.list_templates())

    @app.post('/api/admin/templates')
    @app.post('/api/admin/templates/update')
    def save_template():
        result, status = survey.save_template(request.get_json(), updating=request.path.endswith('/update'))
        return jsonify(result), status

    @app.get('/api/schema')
    def schema():
        with survey.connect() as c:
            return jsonify(survey.get_survey(c, request.args.get('survey', '')))

    @app.get('/api/admin/data')
    @app.get('/api/admin/backup')
    def admin_data():
        data = survey.snapshot(request.args.get('survey', ''))
        if request.path.endswith('/data'):
            data['summary'] = survey.summarize(data)
        response = jsonify(data)
        if request.path.endswith('/backup'):
            response.headers['Content-Disposition'] = f'attachment; filename="nbs-backup-{data["survey_id"]}.json"'
        return response

    @app.get('/api/admin/export')
    def export():
        if not survey.EXPORT_LOCK.acquire(blocking=False):
            return error('Excelを作成中です。しばらくしてからお試しください。', 409)
        try:
            data = survey.snapshot(request.args.get('survey', ''))
            data['summary'] = survey.summarize(data)
            return send_file(export_workbook(data), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                             as_attachment=True, download_name='nbs-survey.xlsx')
        except (LookupError, ValueError):
            raise
        except Exception:
            app.logger.exception('Excel export failed')
            return error('Excelを生成できませんでした。時間をおいて再度お試しください。', 500)
        finally:
            survey.EXPORT_LOCK.release()

    @app.post('/api/responses')
    def respond():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('回答形式が正しくありません。')
        sid = body.get('survey_id')
        with survey.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            current = survey.get_survey(c, sid)
            rid, payload = survey.validate(body, current['schema'])
            encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
            old = c.execute('SELECT payload,survey_id FROM responses WHERE id=?', (rid,)).fetchone()
            if old:
                if old['payload'] != encoded or old['survey_id'] != sid:
                    return error('この受付IDは送信済みです。画面を再読み込みしてください。', 409)
                return jsonify(id=rid, duplicate=True)
            if current['status'] != 'open':
                return error('このアンケートの受付は終了しています。', 409)
            c.execute('INSERT INTO responses (id,created_at,payload,survey_id) VALUES (?,?,?,?)',
                      (rid, survey.now(), encoded, sid))
        return jsonify(id=rid), 201

    @app.post('/api/admin/surveys')
    def create_survey():
        body = request.get_json()
        event = survey.validate_event(body)
        schema = survey.validate_schema(body['schema']) if 'schema' in body else survey.SCHEMA
        sid = body.get('id', '')
        try:
            uuid.UUID(sid)
        except (ValueError, TypeError, AttributeError):
            raise ValueError('作成IDが正しくありません。画面を再読み込みしてください。')
        with survey.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT event,schema_json FROM surveys WHERE id=?', (sid,)).fetchone()
            if old:
                if survey.event_defaults(json.loads(old[0])) != event or json.loads(old[1]) != schema:
                    return error('作成済みのアンケートです。一覧から確認してください。', 409)
                return jsonify(id=sid)
            c.execute('INSERT INTO surveys VALUES (?,?,?,?,?)',
                      (sid, survey.now(), json.dumps(event, ensure_ascii=False), json.dumps(schema, ensure_ascii=False), 'open'))
        return jsonify(id=sid), 201

    @app.post('/api/admin/event')
    @app.post('/api/admin/status')
    def edit_survey():
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError('入力形式が正しくありません。')
        event = survey.validate_event(body) if request.path.endswith('/event') else None
        if event is None and body.get('status') not in ('open', 'closed'):
            raise ValueError('受付状態が正しくありません。')
        with survey.connect() as c:
            survey.get_survey(c, body.get('survey_id'))
            if event is not None:
                c.execute('UPDATE surveys SET event=? WHERE id=?', (json.dumps(event, ensure_ascii=False), body['survey_id']))
            else:
                c.execute('UPDATE surveys SET status=? WHERE id=?', (body['status'], body['survey_id']))
        return jsonify(ok=True)

    files = {'': 'list.html', 'survey': 'index.html', 'admin': 'admin.html',
             'style.css': 'style.css', 'app.js': 'app.js', 'admin.js': 'admin.js', 'list.js': 'list.js', 'builder.js': 'builder.js'}

    @app.get('/')
    @app.get('/<path:page>')
    def page(page=''):
        if page not in files:
            return error('ページが見つかりません。', 404)
        return send_file(ROOT / 'public' / files[page])

    return app
