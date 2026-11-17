import os,sys,json,uuid,tempfile,subprocess,time,urllib.request,urllib.error,http.cookiejar,sqlite3,socket
from pathlib import Path
from fixtures import complete_answers
ROOT=Path(__file__).resolve().parents[1]
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));PORT=probe.getsockname()[1]
BASE=f'http://127.0.0.1:{PORT}'
jar=http.cookiejar.CookieJar();logged=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar));anon=urllib.request.build_opener()
def req(path,body=None,auth=True,headers=None):
    h={'Content-Type':'application/json'} if body is not None else {};h.update(headers or {})
    request=urllib.request.Request(BASE+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=h)
    try:
        with (logged if auth else anon).open(request,timeout=180) as response:return response.status,response.read()
    except urllib.error.HTTPError as e:return e.code,e.read()
def val(path,auth=True):
    code,content=req(path,auth=auth);assert code==200,(code,content);return json.loads(content)
def payload(sid,answers,name='テスト回答'):
    return dict(id=str(uuid.uuid4()),survey_id=sid,name=name,answers=complete_answers(schema,answers),other={})
def seed_legacy(folder):
    c=sqlite3.connect(Path(folder)/'survey.sqlite3')
    c.execute('CREATE TABLE responses (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,payload TEXT NOT NULL)')
    c.execute('CREATE TABLE settings (id INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
    event=dict(title='移行前のアンケート',start='2026-11-11',end='2026-11-14',place='淡路島')
    c.execute('INSERT INTO settings VALUES (1,?)',(json.dumps(event,ensure_ascii=False),))
    rid=str(uuid.uuid4());response=dict(name='既存の回答',answers={'q1':'4：満足','q3':'移行前の原文'},other={})
    c.execute('INSERT INTO responses VALUES (?,?,?)',(rid,'2026-11-16T10:00:00+09:00',json.dumps(response,ensure_ascii=False)));c.commit();c.close();return rid
with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temp:
    legacy_response=seed_legacy(temp)
    env=dict(os.environ);env['ALLOW_ADMIN_SETUP']='true';env.pop('PUBLIC_URL',None);env.pop('ALLOWED_HOSTS',None);env.pop('SECURE_COOKIE',None)
    def launch():
        proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),'--port',str(PORT),'--data-dir',temp],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        for _ in range(50):
            try:
                if req('/api/surveys',auth=False)[0]==200:return proc
            except OSError:time.sleep(.2)
        raise RuntimeError('Server failed to start')
    proc=launch()
    try:
        legacy=val('/api/surveys',False)['surveys'][0]['id']
        for path in ['/api/admin/surveys','/api/admin/data?survey='+legacy,'/api/admin/export?survey='+legacy,'/api/admin/backup?survey='+legacy]:assert req(path,auth=False)[0]==401,path
        assert req('/api/admin/surveys',{},False)[0]==401
        assert req('/api/auth/setup',dict(username='qa-admin',password='short'),False)[0]==400
        credentials=dict(username='qa-admin',password='Local-QA-Password-2026')
        assert req('/api/auth/setup',credentials)[0]==200
        assert req('/api/auth/setup',credentials)[0]==409
        assert val('/api/auth/state')['authenticated']
        assert val('/api/admin/data?survey='+legacy)['responses'][0]['id']==legacy_response
        schema=val('/api/schema?survey='+legacy,False)['schema'];assert len(schema['questions'])==16
        def create(title,start):
            event=dict(id=str(uuid.uuid4()),title=title,start=start,end='',place='淡路島')
            assert req('/api/admin/surveys',event)[0]==201
            assert req('/api/admin/surveys',event)[0]==200
            return event['id']
        sid=create('12月ワーケーション','2026-12-03');older=create('過去のワーケーション','2025-01-03')
        assert [s['id'] for s in val('/api/admin/surveys')['surveys']]==[sid,legacy,older]
        assert all('response_count' not in s for s in val('/api/surveys',False)['surveys'])
        assert req('/api/admin/surveys',dict(id=str(uuid.uuid4()),title='不正日付',start='2026-02-31'))[0]==400
        assert req('/api/schema?survey=missing',auth=False)[0]==404
        assert req('/api/schema',auth=False)[0]==400
        a=payload(sid,{'q1':schema['questions'][0]['options'][0],'q2':schema['questions'][1]['options'][1],'q5':schema['questions'][4]['options'][0],'q7':{'ワークスペース':'2'},'q8':['Web会議用個室'],'q12':{'トイレ':'6以上'},'q14':['サウナ','テラス','個室'],'q3':'=SUM(1,2)\n回答原文。<script>test</script>'})
        b=payload(sid,{'q1':schema['questions'][0]['options'][2],'q5':schema['questions'][4]['options'][2],'q7':{'ワークスペース':'4'},'q8':['特になし'],'q3':'長文の検証です。'*110},'検証 次郎')
        assert req('/api/responses',a,False)[0]==201
        assert req('/api/responses',a,False)[0]==200
        assert req('/api/responses',{**a,'survey_id':legacy},False)[0]==409
        assert req('/api/responses',b,False)[0]==201
        assert req('/api/responses',payload(sid,{'q14':['サウナ','テラス','個室','大浴場']}),False)[0]==400
        assert req('/api/responses',payload(sid,{'q8':['特になし','Wi-Fi']}),False)[0]==400
        assert req('/api/responses',{**payload(sid,{}),'answers':{}},False)[0]==400
        assert req('/api/responses',payload(sid,{'q3':'a'}),False,{'Origin':'https://evil.example'})[0]==403
        d=val('/api/admin/data?survey='+sid);s=d['summary'];assert s['total']==2 and s['questions']['q1']['average']==4 and s['communication_rate']==.5
        assert val('/api/admin/data?survey='+legacy)['summary']['total']==1
        assert val('/api/admin/data?survey='+older)['summary']['total']==0
        code,content=req('/api/admin/export?survey='+sid);assert code==200,content.decode(errors='replace')
        out=Path(temp)/'multi-export.xlsx';out.write_bytes(content)
        import openpyxl
        w=openpyxl.load_workbook(out,data_only=True)
        assert w['集計サマリー']['B5'].value=='12月ワーケーション'
        assert w['集計サマリー']['B8'].value==2 and w['集計サマリー']['B9'].value==4 and w['集計サマリー']['B11'].value==.5
        rows=list(w['自由記述一覧'].iter_rows(min_row=5,values_only=True))
        assert ''.join(str(r[6]) for r in rows if r[0]==b['id'] and r[2]=='Q3')==b['answers']['q3']
        assert all(r[0]!=legacy_response for r in rows)
        assert len(w.sheetnames)==6
        assert val('/api/admin/backup?survey='+sid)['survey_id']==sid
        assert req('/api/admin/status',dict(survey_id=sid,status='closed'))[0]==200
        assert req('/api/responses',payload(sid,{'q3':'受付終了後'}),False)[0]==409
        assert req('/api/responses',a,False)[0]==200
        assert val('/api/schema?survey='+sid,False)['status']=='closed'
        assert req('/api/admin/status',dict(survey_id=sid,status='open'))[0]==200
        assert req('/api/admin/event',dict(survey_id=older,title='過去の回を修正',start='2027-01-01',end='',place=''))[0]==200
        assert val('/api/admin/surveys')['surveys'][0]['id']==older
        assert req('/api/auth/logout',{})[0]==200
        assert req('/api/admin/surveys')[0]==401
        assert req('/api/auth/login',dict(username='qa-admin',password='wrong'))[0]==401
        assert req('/api/auth/login',credentials)[0]==200
        proc.terminate();proc.wait(10);proc=launch()
        assert len(val('/api/admin/surveys')['surveys'])==3
        assert val('/api/admin/data?survey='+legacy)['responses'][0]['id']==legacy_response
        assert val('/api/admin/data?survey='+sid)['summary']['total']==2
        with sqlite3.connect(Path(temp)/'survey.sqlite3') as c:
            stored=c.execute('SELECT password_hash FROM admin_account').fetchone()[0];assert stored!=credentials['password'] and len(stored)==128
            c.execute('UPDATE sessions SET expires_at=0')
        c.close()
        assert req('/api/admin/surveys')[0]==401
        for _ in range(5):assert req('/api/auth/login',dict(username='qa-admin',password='wrong'))[0]==401
        assert req('/api/auth/login',credentials)[0]==429
        print('PASS: legacy migration, ID/password setup/login/logout/expiry/rate limit, protected APIs, survey creation/retry, date ordering, isolated responses/exports, validation, close/reopen, restart persistence')
    finally:
        proc.terminate();proc.wait(10)
        out,err=proc.communicate()
        if err:print(err.decode(errors='replace')[-3000:])
