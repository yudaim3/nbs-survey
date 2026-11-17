from flask import current_app
from pathlib import Path

from datetime import datetime, timezone, timedelta
import json, sqlite3, uuid, threading, hashlib

from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'schema.json').read_text(encoding='utf-8'))
DEFAULT_EVENT = dict(title='淡路島ワーケーション', start='', end='', place='')
JST = timezone(timedelta(hours=9))
EXPORT_LOCK = threading.Lock()

def now(): return datetime.now(JST).isoformat(timespec='seconds')
@contextmanager
def connect():
    c = sqlite3.connect(current_app.config['DATABASE'], timeout=15)
    c.row_factory = sqlite3.Row
    try:
        with c:yield c
    finally:c.close()

def initialize():
    Path(current_app.config['DATABASE']).parent.mkdir(parents=True, exist_ok=True)
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
        if value is None or value=='' or value==[] or value=={}: raise ValueError(f"Q{q['number']}に回答してください。")
        kind=q['type']; options=q.get('options',[])
        if kind=='text':
            if not isinstance(value,str) or len(value)>5000: raise ValueError(f"Q{q['number']}は5000文字以内で入力してください。")
            value=value.strip()
            if not value: raise ValueError(f"Q{q['number']}に回答してください。")
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
            missing=next((option for option in options if option not in value),None)
            if missing is not None: raise ValueError(f"Q{q['number']}の「{missing}」に回答してください。")
        if value: result[q['id']]=value
    name=body.get('name','')
    if not isinstance(name,str) or len(name)>100: raise ValueError('回答者名は100文字以内で入力してください。')
    if not name.strip(): raise ValueError('回答者名を入力してください。')
    if '　' in name: raise ValueError('スペースは半角にしてください。')
    other=body.get('other',{})
    if not isinstance(other,dict): raise ValueError('補足の形式が正しくありません。')
    cleaned={}
    for key,value in other.items():
        if key not in ['q8','q11','q13','q14'] or not isinstance(value,str) or len(value)>2000: raise ValueError('その他の補足は2000文字以内で入力してください。')
        selected=result.get(key,[])
        if (selected=='その他' or isinstance(selected,list) and 'その他' in selected) and value.strip(): cleaned[key]=value.strip()
    for q in schema['questions']:
        selected=result[q['id']]
        if (selected=='その他' or isinstance(selected,list) and 'その他' in selected) and q['id'] not in cleaned:
            raise ValueError(f"Q{q['number']}の「その他の内容」を入力してください。")
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
