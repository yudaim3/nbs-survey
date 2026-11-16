from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from datetime import datetime, timezone, timedelta
import argparse, json, sqlite3, uuid, os, subprocess, tempfile, threading, socket, secrets, hashlib, hmac, time, re
from http.cookies import SimpleCookie
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'schema.json').read_text(encoding='utf-8'))
DEFAULT_EVENT = dict(title='淡路島ワーケーション', start='', end='', place='')
JST = timezone(timedelta(hours=9))
EXPORT_LOCK = threading.Lock()

def now(): return datetime.now(JST).isoformat(timespec='seconds')
@contextmanager
def connect():
    c = sqlite3.connect(DB, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:yield c
    finally:c.close()

def initialize():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS responses (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
        c.execute('INSERT OR IGNORE INTO settings VALUES (1,?)', (json.dumps(DEFAULT_EVENT,ensure_ascii=False),))
        c.execute('CREATE TABLE IF NOT EXISTS surveys (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, event TEXT NOT NULL, schema_json TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN (\'open\',\'closed\')))')
        if 'survey_id' not in {row['name'] for row in c.execute('PRAGMA table_info(responses)')}:
            c.execute('ALTER TABLE responses ADD COLUMN survey_id TEXT REFERENCES surveys(id)')
        if not c.execute('SELECT 1 FROM surveys LIMIT 1').fetchone():
            legacy_id=str(uuid.uuid4())
            stored=json.loads(c.execute('SELECT payload FROM settings WHERE id=1').fetchone()[0])
            event={key:stored.get(key,value) for key,value in DEFAULT_EVENT.items()}
            c.execute('INSERT INTO surveys VALUES (?,?,?,?,?)',(legacy_id,now(),json.dumps(event,ensure_ascii=False),json.dumps(SCHEMA,ensure_ascii=False),'open'))
            c.execute('UPDATE responses SET survey_id=? WHERE survey_id IS NULL',(legacy_id,))
        c.execute('CREATE INDEX IF NOT EXISTS responses_survey ON responses(survey_id,created_at)')
        c.execute('CREATE TABLE IF NOT EXISTS admin_account (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_attempts (client TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at REAL NOT NULL)')

def password_hash(password,salt):
    return hashlib.scrypt(password.encode('utf-8'),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=64).hex()

def get_survey(c, survey_id):
    if not isinstance(survey_id,str) or not survey_id:raise ValueError('アンケートを選択してください。')
    row=c.execute('SELECT * FROM surveys WHERE id=?',(survey_id,)).fetchone()
    if row is None:raise LookupError('アンケートが見つかりません。')
    return dict(id=row['id'],created_at=row['created_at'],event=json.loads(row['event']),schema=json.loads(row['schema_json']),status=row['status'])

def list_surveys(admin=False):
    with connect() as c:
        rows=c.execute('SELECT s.*,COUNT(r.id) AS response_count FROM surveys s LEFT JOIN responses r ON r.survey_id=s.id GROUP BY s.id').fetchall()
    result=[]
    for row in rows:
        item=dict(id=row['id'],created_at=row['created_at'],event=json.loads(row['event']),status=row['status'])
        if admin:item['response_count']=row['response_count']
        result.append(item)
    return sorted(result,key=lambda x:(bool(x['event']['start']),x['event']['start'],x['created_at'],x['id']),reverse=True)

def validate_event(body):
    if not isinstance(body,dict):raise ValueError('開催情報が正しくありません。')
    event={}
    for key in DEFAULT_EVENT:
        value=body.get(key,'')
        if not isinstance(value,str) or len(value)>{'title':200,'place':500,'start':10,'end':10}[key]:raise ValueError('開催情報の入力が正しくありません。')
        event[key]=value.strip()
    if not event['title']:raise ValueError('開催名を入力してください。')
    if not event['start']:raise ValueError('開催日（開始日）を入力してください。')
    for key in ['start','end']:
        if event[key]:
            try:event[key]=datetime.strptime(event[key],'%Y-%m-%d').date().isoformat()
            except ValueError:raise ValueError('日付を正しく入力してください。')
    if event['end'] and event['start']>event['end']:raise ValueError('終了日は開始日以降にしてください。')
    return event

def validate(body,schema=SCHEMA):
    if not isinstance(body,dict): raise ValueError('回答形式が正しくありません。')
    rid = body.get('id','')
    try: uuid.UUID(rid)
    except (ValueError,TypeError,AttributeError): raise ValueError('受付IDが正しくありません。画面を再読み込みしてください。')
    answers=body.get('answers',{})
    if not isinstance(answers,dict): raise ValueError('回答形式が正しくありません。')
    if set(answers)-{q['id'] for q in schema['questions']}: raise ValueError('未知の設問があります。')
    result={}
    for q in schema['questions']:
        value=answers.get(q['id'])
        if value is None or value=='' or value==[] or value=={}: continue
        kind=q['type']; options=q.get('options',[])
        if kind=='text':
            if not isinstance(value,str) or len(value)>5000: raise ValueError(f"Q{q['number']}は5000文字以内で入力してください。")
            value=value.strip()
        elif kind=='single':
            if not isinstance(value,str) or value not in options: raise ValueError(f"Q{q['number']}の選択肢が正しくありません。")
        elif kind=='multi':
            if not isinstance(value,list) or any(not isinstance(v,str) or v not in options for v in value) or len(value)!=len(set(value)): raise ValueError(f"Q{q['number']}の選択肢が正しくありません。")
            if len(value)>q.get('max',len(options)): raise ValueError(f"Q{q['number']}は最大{q['max']}つまでです。")
            if '特になし' in value and len(value)>1: raise ValueError('Q8の「特になし」は他の項目と同時に選択できません。')
            value=[v for v in options if v in value]
        else:
            valid=['1','2','3','4','5'] if kind=='rating' else ['1','2','3','4','5','6以上']
            if not isinstance(value,dict) or any(k not in options or v not in valid for k,v in value.items()): raise ValueError(f"Q{q['number']}の値が正しくありません。")
        if value: result[q['id']]=value
    name=body.get('name','')
    if not isinstance(name,str) or len(name)>100: raise ValueError('回答者名は100文字以内で入力してください。')
    other=body.get('other',{})
    if not isinstance(other,dict): raise ValueError('補足の形式が正しくありません。')
    cleaned={}
    for key,value in other.items():
        if key not in ['q8','q11','q13','q14'] or not isinstance(value,str) or len(value)>2000: raise ValueError('その他の補足は2000文字以内で入力してください。')
        selected=result.get(key,[])
        if (selected=='その他' or isinstance(selected,list) and 'その他' in selected) and value.strip(): cleaned[key]=value.strip()
    if not result: raise ValueError('少なくとも1つの設問に回答してください。')
    return rid,dict(name=name.strip(),answers=result,other=cleaned)

def snapshot(survey_id):
    with connect() as c:
        c.execute('BEGIN')
        survey=get_survey(c,survey_id)
        records=[dict(id=r['id'],created_at=r['created_at'],**json.loads(r['payload'])) for r in c.execute('SELECT * FROM responses WHERE survey_id=? ORDER BY created_at,id',(survey_id,))]
    return dict(survey_id=survey_id,event=survey['event'],status=survey['status'],responses=records,schema=survey['schema'],exported_at=now())

def summarize(data):
    rs=data['responses']; total=len(rs); result={}
    for q in data['schema']['questions']:
        key=q['id']; vals=[r['answers'][key] for r in rs if key in r['answers']]
        item=dict(answered=len(vals),missing=total-len(vals))
        if q['type'] in ['single','multi']:
            item['counts']={o:sum(v==o if q['type']=='single' else o in v for v in vals) for o in q['options']}
        if key in ['q1','q2']:
            item['average']=sum(int(v[0]) for v in vals)/len(vals) if vals else None
        if q['type'] in ['rating','count']:
            rows=[]
            for option in q['options']:
                vs=[v[option] for v in vals if option in v]
                row=dict(label=option,answered=len(vs),missing=total-len(vs))
                if q['type']=='rating': row.update(average=sum(map(int,vs))/len(vs) if vs else None,low=sum(int(v)<=2 for v in vs))
                else: row['counts']={v:vs.count(v) for v in ['1','2','3','4','5','6以上']}
                rows.append(row)
            item['rows']=rows
        result[key]=item
    q5=result['q5']; positive=sum(q5['counts'][o] for o in data['schema']['questions'][4]['options'][:2])
    return dict(total=total,questions=result,communication_rate=positive/q5['answered'] if q5['answered'] else None)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args): pass
    def reply(self,status,body,kind='application/json; charset=utf-8',extra=None):
        if isinstance(body,(dict,list)): body=json.dumps(body,ensure_ascii=False).encode('utf-8')
        elif isinstance(body,str): body=body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for k,v in (extra or {}).items(): self.send_header(k,v)
        self.end_headers(); self.wfile.write(body)
    def allowed(self):
        host=self.headers.get('Host','')
        if host not in HOSTS: self.reply(403,dict(error='このホストからのアクセスは許可されていません。')); return False
        return True
    def local_only(self):
        if self.client_address[0] not in ['127.0.0.1','::1']: self.reply(403,dict(error='管理画面は起動したPCからのみ利用できます。')); return False
        return True
    def session_hash(self):
        try:
            cookies=SimpleCookie();cookies.load(self.headers.get('Cookie',''));token=cookies.get('awaji_admin')
            return hashlib.sha256(token.value.encode()).hexdigest() if token else ''
        except Exception:return ''
    def authenticated(self):
        with connect() as c:return c.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>?',(self.session_hash(),time.time())).fetchone() is not None
    def admin(self):
        if not self.local_only():return False
        if not self.authenticated():self.reply(401,dict(error='管理者ログインが必要です。'));return False
        return True
    def issue_session(self,c):
        token=secrets.token_urlsafe(32)
        c.execute('DELETE FROM sessions WHERE expires_at<=? OR token_hash=?',(time.time(),self.session_hash()))
        c.execute('INSERT INTO sessions VALUES (?,?)',(hashlib.sha256(token.encode()).hexdigest(),time.time()+8*3600))
        return {'Set-Cookie':f'awaji_admin={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800'}
    def auth_post(self,path,body):
        if not self.local_only():return
        if not isinstance(body,dict):raise ValueError('入力形式が正しくありません。')
        if path=='/api/auth/logout':
            with connect() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(self.session_hash(),))
            return self.reply(200,dict(ok=True),extra={'Set-Cookie':'awaji_admin=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0'})
        if path not in ['/api/auth/setup','/api/auth/login']:return self.reply(404,dict(error='APIが見つかりません。'))
        username=body.get('username','');password=body.get('password','')
        if not isinstance(username,str) or not isinstance(password,str) or len(username)>80 or len(password)>128:raise ValueError('IDまたはパスワードの形式が正しくありません。')
        username=username.strip()
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            account=c.execute('SELECT * FROM admin_account WHERE id=1').fetchone()
            if path=='/api/auth/setup':
                if account:return self.reply(409,dict(error='管理者は設定済みです。ログインしてください。'))
                if not re.fullmatch(r'[A-Za-z0-9_.@-]{3,80}',username):raise ValueError('管理者IDは半角英数字・_ . @ - を使い、3〜80文字で設定してください。')
                if len(password)<12:raise ValueError('パスワードは12文字以上で設定してください。')
                salt=secrets.token_hex(16)
                c.execute('INSERT INTO admin_account VALUES (1,?,?,?)',(username,salt,password_hash(password,salt)))
            else:
                attempt=c.execute('SELECT * FROM auth_attempts WHERE client=?',(self.client_address[0],)).fetchone()
                if attempt and attempt['reset_at']>time.time() and attempt['attempts']>=5:return self.reply(429,dict(error='ログイン失敗が続いたため、15分ほど待ってからお試しください。'))
                salt=account['salt'] if account else '0'*32
                candidate=password_hash(password,salt)
                if not account or not (hmac.compare_digest(account['username'].encode(),username.encode()) & hmac.compare_digest(account['password_hash'],candidate)):
                    count=attempt['attempts']+1 if attempt and attempt['reset_at']>time.time() else 1
                    reset=attempt['reset_at'] if attempt and attempt['reset_at']>time.time() else time.time()+900
                    c.execute('INSERT OR REPLACE INTO auth_attempts VALUES (?,?,?)',(self.client_address[0],count,reset))
                    c.commit()
                    return self.reply(401,dict(error='管理者IDまたはパスワードが正しくありません。'))
                c.execute('DELETE FROM auth_attempts WHERE client=?',(self.client_address[0],))
            cookie=self.issue_session(c)
        return self.reply(200,dict(ok=True),extra=cookie)
    def do_GET(self):
        try:self.get()
        except LookupError as e:self.reply(404,dict(error=str(e)))
        except ValueError as e:self.reply(400,dict(error=str(e)))
        except sqlite3.Error:self.reply(500,dict(error='データを読み込めませんでした。'))
    def get(self):
        if not self.allowed(): return
        path=urlsplit(self.path).path
        survey_id=parse_qs(urlsplit(self.path).query).get('survey',[''])[0]
        if path.startswith('/api/admin/'):
            if not self.admin(): return
        if path=='/admin' and not self.local_only():return
        if path=='/api/auth/state':
            if not self.local_only():return
            with connect() as c:configured=c.execute('SELECT 1 FROM admin_account').fetchone() is not None
            return self.reply(200,dict(configured=configured,authenticated=self.authenticated()))
        if path in ['/api/surveys','/api/admin/surveys']:
            return self.reply(200,dict(surveys=list_surveys(admin=path.startswith('/api/admin/'))))
        if path=='/api/schema':
            with connect() as c:survey=get_survey(c,survey_id)
            return self.reply(200,survey)
        if path=='/api/admin/data':
            data=snapshot(survey_id); data['summary']=summarize(data); return self.reply(200,data)
        if path=='/api/admin/backup':
            return self.reply(200,snapshot(survey_id),extra={'Content-Disposition':f'attachment; filename="awaji-backup-{survey_id}.json"'})
        if path=='/api/admin/export':
            if not EXPORT_LOCK.acquire(blocking=False): return self.reply(409,dict(error='Excelを作成中です。しばらくしてからお試しください。'))
            try:
                data=snapshot(survey_id); data['summary']=summarize(data)
                with tempfile.TemporaryDirectory(prefix='awaji-export-') as temp:
                    target=Path(temp)/'survey.xlsx'
                    proc=subprocess.run([os.environ.get('AWAJI_NODE','node'),str(ROOT/'export.mjs'),str(target)],input=json.dumps(data,ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=180,cwd=ROOT)
                    if proc.returncode: print(proc.stderr[-1500:],flush=True); raise RuntimeError('Excel生成に失敗しました。起動用ファイルから再起動してください。')
                    return self.reply(200,target.read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',{'Content-Disposition':f'attachment; filename="awaji-survey-{datetime.now(JST):%Y%m%d-%H%M%S}.xlsx"'})
            except (RuntimeError,OSError,subprocess.TimeoutExpired) as e: return self.reply(500,dict(error=str(e)))
            finally: EXPORT_LOCK.release()
        files={'/':'list.html','/survey':'index.html','/admin':'admin.html','/style.css':'style.css','/app.js':'app.js','/admin.js':'admin.js','/list.js':'list.js'}
        if path not in files:return self.reply(404,dict(error='ページが見つかりません。'))
        file=ROOT/'public'/files[path]
        kinds={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8'}
        return self.reply(200,file.read_bytes(),kinds[file.suffix])
    def do_POST(self):
        if not self.allowed():return
        origin=self.headers.get('Origin')
        if origin and origin!=f"http://{self.headers.get('Host')}": return self.reply(403,dict(error='送信元が一致しません。'))
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.reply(415,dict(error='JSON形式が必要です。'))
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<1 or length>250000:raise ValueError('送信サイズが上限を超えています。')
            body=json.loads(self.rfile.read(length))
            path=urlsplit(self.path).path
            if path.startswith('/api/auth/'):return self.auth_post(path,body)
            if path=='/api/responses':
                if not isinstance(body,dict):raise ValueError('回答形式が正しくありません。')
                survey_id=body.get('survey_id')
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    survey=get_survey(c,survey_id)
                    rid,payload=validate(body,survey['schema']); encoded=json.dumps(payload,ensure_ascii=False,sort_keys=True)
                    old=c.execute('SELECT payload,survey_id FROM responses WHERE id=?',(rid,)).fetchone()
                    if old:
                        if old['payload']!=encoded or old['survey_id']!=survey_id:return self.reply(409,dict(error='この受付IDは送信済みです。画面を再読み込みしてください。'))
                        return self.reply(200,dict(id=rid,duplicate=True))
                    if survey['status']!='open':return self.reply(409,dict(error='このアンケートの受付は終了しています。'))
                    c.execute('INSERT INTO responses (id,created_at,payload,survey_id) VALUES (?,?,?,?)',(rid,now(),encoded,survey_id))
                return self.reply(201,dict(id=rid))
            if path=='/api/admin/surveys':
                if not self.admin():return
                event=validate_event(body)
                survey_id=body.get('id','')
                try:uuid.UUID(survey_id)
                except (ValueError,TypeError,AttributeError):raise ValueError('作成IDが正しくありません。画面を再読み込みしてください。')
                with connect() as c:
                    c.execute('BEGIN IMMEDIATE')
                    old=c.execute('SELECT event FROM surveys WHERE id=?',(survey_id,)).fetchone()
                    if old:
                        if json.loads(old[0])!=event:return self.reply(409,dict(error='作成済みのアンケートです。一覧から確認してください。'))
                        return self.reply(200,dict(id=survey_id))
                    c.execute('INSERT INTO surveys VALUES (?,?,?,?,?)',(survey_id,now(),json.dumps(event,ensure_ascii=False),json.dumps(SCHEMA,ensure_ascii=False),'open'))
                return self.reply(201,dict(id=survey_id))
            if path=='/api/admin/event':
                if not self.admin():return
                event=validate_event(body)
                with connect() as c:
                    get_survey(c,body.get('survey_id'))
                    c.execute('UPDATE surveys SET event=? WHERE id=?',(json.dumps(event,ensure_ascii=False),body['survey_id']))
                return self.reply(200,dict(ok=True))
            if path=='/api/admin/status':
                if not self.admin():return
                if not isinstance(body,dict) or body.get('status') not in ['open','closed']:raise ValueError('受付状態が正しくありません。')
                with connect() as c:
                    get_survey(c,body.get('survey_id'))
                    c.execute('UPDATE surveys SET status=? WHERE id=?',(body['status'],body['survey_id']))
                return self.reply(200,dict(ok=True))
            return self.reply(404,dict(error='APIが見つかりません。'))
        except (ValueError,TypeError,UnicodeDecodeError) as e:return self.reply(400,dict(error=str(e)))
        except LookupError as e:return self.reply(404,dict(error=str(e)))
        except sqlite3.Error:return self.reply(500,dict(error='保存できませんでした。時間をおいて再送してください。'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--host',default='127.0.0.1');p.add_argument('--data-dir',default=str(ROOT/'data'));args=p.parse_args()
    DB=Path(args.data_dir)/'survey.sqlite3';initialize()
    HOSTS={f'localhost:{args.port}',f'127.0.0.1:{args.port}'}
    if args.host=='0.0.0.0':
        HOSTS.update(f'{ip}:{args.port}' for ip in socket.gethostbyname_ex(socket.gethostname())[2])
    else:HOSTS.add(f'{args.host}:{args.port}')
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'回答画面: http://localhost:{args.port}/\n管理画面: http://localhost:{args.port}/admin\n保存先: {DB}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
