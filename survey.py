from flask import current_app
from pathlib import Path

from datetime import datetime, timezone, timedelta
import json, sqlite3, uuid, threading, hashlib, math, re

from contextlib import contextmanager

ROOT = Path(__file__).resolve().parent
SCHEMA = json.loads((ROOT / 'schema.json').read_text(encoding='utf-8'))
DEFAULT_EVENT = dict(title='淡路島ワーケーション', start='', end='', place='')
JST = timezone(timedelta(hours=9))
EXPORT_LOCK = threading.Lock()
CATEGORIES = ['ワーケーション', '飲み会', 'その他']

def list_categories():
    with connect() as c:
        return [row['name'] for row in c.execute('SELECT name FROM categories ORDER BY rowid')]

def add_category(name):
    if not isinstance(name, str) or not name.strip(): raise ValueError('カテゴリー名を入力してください。')
    name = name.strip()
    if len(name) > 50 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError('カテゴリー名は改行を含めず、50文字以内で入力してください。')
    with connect() as c:
        created = c.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (name,)).rowcount == 1
    return name, created

def event_defaults(event):
    return {**event, 'category': event.get('category', 'ワーケーション')}

PARTY_SCHEMA = dict(intro='今後の開催の参考にするため、ご意見をお聞かせください。', questions=[
    dict(title='今回の飲み会の満足度を教えてください。',type='scale',required=True),
    dict(title='良かった点を選んでください。',type='multi',options=['料理','飲み物','会場','交流','その他'],required=True),
    dict(title='次回も参加したいですか？',type='single',options=['参加したい','どちらともいえない','参加しない'],required=True),
    dict(title='次回の希望予算を教えてください。',type='select',options=['3,000円未満','3,000〜5,000円','5,000円以上'],required=False),
    dict(title='感想や改善してほしい点を教えてください。',type='text',required=False),
])

def list_templates():
    with connect() as c:
        return [dict(id=r['id'],name=r['name'],revision=r['revision'],schema=json.loads(r['schema_json']))
                for r in c.execute('SELECT * FROM templates ORDER BY rowid')]

def save_template(body, updating=False):
    if not isinstance(body, dict): raise ValueError('入力形式が正しくありません。')
    tid, name = body.get('id'), body.get('name')
    try: uuid.UUID(tid)
    except (ValueError,TypeError,AttributeError): raise ValueError('ひな形IDが正しくありません。')
    if not isinstance(name,str) or not name.strip() or len(name.strip())>100 or any(ord(ch)<32 for ch in name):
        raise ValueError('ひな形名を改行なし・100文字以内で入力してください。')
    name = name.strip()
    schema = validate_schema(body.get('schema'))
    encoded = json.dumps(schema,ensure_ascii=False,sort_keys=True)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM templates WHERE id=?',(tid,)).fetchone()
        if c.execute('SELECT 1 FROM templates WHERE name=? AND id<>?',(name,tid)).fetchone():
            return dict(error='同じ名前のひな形があります。別の名前を入力してください。'),409
        if updating:
            if old is None: raise LookupError('ひな形が見つかりません。')
            revision = body.get('revision')
            if type(revision) is not int or revision<1: raise ValueError('ひな形を読み込み直してください。')
            if old['name']==name and json.loads(old['schema_json'])==schema:
                return dict(id=tid,name=name,revision=old['revision']),200
            if revision!=old['revision']:
                return dict(error='このひな形は別の画面で更新されています。入力内容を別名で新規登録するか、読み込み直してください。'),409
            revision+=1
            c.execute('UPDATE templates SET name=?,schema_json=?,revision=?,updated_at=? WHERE id=?',(name,encoded,revision,now(),tid))
        else:
            if old:
                if old['name']==name and json.loads(old['schema_json'])==schema:
                    return dict(id=tid,name=name,revision=old['revision']),200
                return dict(error='このひな形は登録済みです。読み込み直してください。'),409
            revision=1
            c.execute('INSERT INTO templates VALUES (?,?,?,?,?,?)',(tid,name,encoded,revision,now(),now()))
    return dict(id=tid,name=name,revision=revision),200 if updating else 201

def validate_schema(body):
    """Only accept bounded, declarative form definitions; never executable content."""
    if not isinstance(body, dict): raise ValueError('設問の形式が正しくありません。')
    intro = body.get('intro', '')
    if not isinstance(intro, str) or len(intro) > 2000: raise ValueError('説明文は2000文字以内で入力してください。')
    questions = body.get('questions')
    if not isinstance(questions, list) or not 1 <= len(questions) <= 50: raise ValueError('質問は1〜50問で作成してください。')
    result = []
    for number, q in enumerate(questions, 1):
        if not isinstance(q, dict): raise ValueError('設問の形式が正しくありません。')
        title, kind, required = q.get('title'), q.get('type'), q.get('required', True)
        if not isinstance(title, str) or not title.strip() or len(title) > 500: raise ValueError(f'Q{number}の質問文を500文字以内で入力してください。')
        if kind not in ('text', 'shorttext', 'single', 'select', 'multi', 'number', 'date', 'scale', 'rating', 'count'): raise ValueError('回答形式が正しくありません。')
        if type(required) is not bool: raise ValueError('必須・任意の指定が正しくありません。')
        item = dict(id=f'q{number}', number=number, section=1, title=title.strip(), type=kind, required=required)
        if kind in ('single', 'select', 'multi', 'rating', 'count'):
            options = q.get('options')
            if not isinstance(options, list) or not 1 <= len(options) <= 50 or any(not isinstance(o, str) or not o.strip() or len(o) > 200 for o in options): raise ValueError(f'Q{number}の選択肢を1〜50件、各200文字以内で入力してください。')
            options = [o.strip() for o in options]
            if len(set(options)) != len(options): raise ValueError(f'Q{number}の選択肢が重複しています。')
            item['options'] = options
            if kind == 'multi' and q.get('max') is not None:
                maximum = q['max']
                if type(maximum) is not int or not 1 <= maximum <= len(options): raise ValueError(f'Q{number}の最大選択数が正しくありません。')
                item['max'] = maximum
        result.append(item)
    return dict(version=2, intro=intro.strip(), sections=['アンケート'], questions=result)

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
        c.execute('CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY NOT NULL)')
        c.executemany('INSERT OR IGNORE INTO categories (name) VALUES (?)', [(name,) for name in CATEGORIES])
        for row in c.execute('SELECT event FROM surveys').fetchall():
            category = event_defaults(json.loads(row['event']))['category']
            c.execute('INSERT OR IGNORE INTO categories (name) VALUES (?)', (category,))
        c.execute('CREATE TABLE IF NOT EXISTS templates (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, schema_json TEXT NOT NULL, revision INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)')
        for key,name,definition in [('workation','ワーケーション',SCHEMA),('party','飲み会',PARTY_SCHEMA)]:
            tid=str(uuid.uuid5(uuid.NAMESPACE_URL,'nbs-survey-template:'+key))
            if not c.execute('SELECT 1 FROM templates WHERE id=?',(tid,)).fetchone():
                c.execute('INSERT INTO templates VALUES (?,?,?,?,?,?)',(tid,name,json.dumps(validate_schema(definition),ensure_ascii=False,sort_keys=True),1,now(),now()))
        c.execute('CREATE TABLE IF NOT EXISTS admin_account (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires_at REAL NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_attempts (client TEXT PRIMARY KEY, attempts INTEGER NOT NULL, reset_at REAL NOT NULL)')

def password_hash(password,salt):
    return hashlib.scrypt(password.encode('utf-8'),salt=bytes.fromhex(salt),n=16384,r=8,p=1,dklen=64).hex()

def get_survey(c, survey_id):
    if not isinstance(survey_id,str) or not survey_id:raise ValueError('アンケートを選択してください。')
    row=c.execute('SELECT * FROM surveys WHERE id=?',(survey_id,)).fetchone()
    if row is None:raise LookupError('アンケートが見つかりません。')
    return dict(id=row['id'],created_at=row['created_at'],event=event_defaults(json.loads(row['event'])),schema=json.loads(row['schema_json']),status=row['status'])

def list_surveys(admin=False):
    with connect() as c:
        rows=c.execute('SELECT s.*,COUNT(r.id) AS response_count FROM surveys s LEFT JOIN responses r ON r.survey_id=s.id GROUP BY s.id').fetchall()
    result=[]
    for row in rows:
        item=dict(id=row['id'],created_at=row['created_at'],event=event_defaults(json.loads(row['event'])),status=row['status'])
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
    category = body.get('category', 'ワーケーション')
    if not isinstance(category, str) or category not in list_categories(): raise ValueError('カテゴリーを選択してください。')
    event['category'] = category
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
        if value is None or value=='' or value==[] or value=={} or isinstance(value,str) and not value.strip():
            if q.get('required', True): raise ValueError(f"Q{q['number']}に回答してください。")
            continue
        kind=q['type']; options=q.get('options',[])
        if kind in ('text','shorttext'):
            limit = 5000 if kind == 'text' else 300
            if not isinstance(value,str) or len(value)>limit: raise ValueError(f"Q{q['number']}は{limit}文字以内で入力してください。")
            value=value.strip()
            if not value: raise ValueError(f"Q{q['number']}に回答してください。")
        elif kind in ('single','select'):
            if not isinstance(value,str) or value not in options: raise ValueError(f"Q{q['number']}の選択肢が正しくありません。")
        elif kind=='multi':
            if not isinstance(value,list) or any(not isinstance(v,str) or v not in options for v in value) or len(value)!=len(set(value)): raise ValueError(f"Q{q['number']}の選択肢が正しくありません。")
            if len(value)>q.get('max',len(options)): raise ValueError(f"Q{q['number']}は最大{q['max']}つまでです。")
            if '特になし' in value and len(value)>1: raise ValueError(f"Q{q['number']}の「特になし」は他の項目と同時に選択できません。")
            value=[v for v in options if v in value]
        elif kind in ('number', 'scale'):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or abs(value)>1e12 or not math.isfinite(value): raise ValueError(f"Q{q['number']}に有効な数値を入力してください。")
            if kind=='scale' and value not in (1,2,3,4,5): raise ValueError(f"Q{q['number']}は1〜5で回答してください。")
        elif kind=='date':
            if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError(f"Q{q['number']}に日付を入力してください。")
            try: datetime.strptime(value,'%Y-%m-%d')
            except ValueError: raise ValueError(f"Q{q['number']}の日付が正しくありません。")
        else:
            valid=['1','2','3','4','5'] if kind=='rating' else ['1','2','3','4','5','6以上']
            if not isinstance(value,dict) or any(k not in options or v not in valid for k,v in value.items()): raise ValueError(f"Q{q['number']}の値が正しくありません。")
            missing=next((option for option in options if option not in value),None)
            if missing is not None and q.get('required', True): raise ValueError(f"Q{q['number']}の「{missing}」に回答してください。")
        result[q['id']]=value
    name=body.get('name','')
    if not isinstance(name,str) or len(name)>100: raise ValueError('回答者名は100文字以内で入力してください。')
    if not name.strip(): raise ValueError('回答者名を入力してください。')
    if '　' in name: raise ValueError('スペースは半角にしてください。')
    other=body.get('other',{})
    if not isinstance(other,dict): raise ValueError('補足の形式が正しくありません。')
    cleaned={}
    for key,value in other.items():
        if key not in {q['id'] for q in schema['questions']} or not isinstance(value,str) or len(value)>2000: raise ValueError('その他の補足は2000文字以内で入力してください。')
        selected=result.get(key,[])
        if (selected=='その他' or isinstance(selected,list) and 'その他' in selected) and value.strip(): cleaned[key]=value.strip()
    for q in schema['questions']:
        selected=result.get(q['id'])
        if q['type'] in ('single','select','multi') and 'その他' in q.get('options',[]) and (selected=='その他' or isinstance(selected,list) and 'その他' in selected) and q['id'] not in cleaned:
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
        if q['type'] in ['single','select','multi']:
            item['counts']={o:sum(v==o if q['type']!='multi' else o in v for v in vals) for o in q['options']}
        if data['schema'].get('version',1)==1 and key in ['q1','q2']:
            item['average']=sum(int(v[0]) for v in vals)/len(vals) if vals else None
        if q['type'] in ('number','scale'):
            item.update(average=sum(vals)/len(vals) if vals else None, minimum=min(vals) if vals else None, maximum=max(vals) if vals else None)
        if q['type']=='scale': item['counts']={str(n):vals.count(n) for n in range(1,6)}
        if q['type']=='date': item['counts']={v:vals.count(v) for v in sorted(set(vals))}
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
    rate=None
    if data['schema'].get('version',1)==1:
        q5=result['q5']; positive=sum(q5['counts'][o] for o in data['schema']['questions'][4]['options'][:2])
        rate=positive/q5['answered'] if q5['answered'] else None
    return dict(total=total,questions=result,communication_rate=rate)
