"""Saved templates must be editable without mutating issued surveys or answers."""
import copy
import io
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from webapp import create_app
from data_transfer import copy_database
from openpyxl import load_workbook


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config=dict(TESTING=True,DATABASE=str(Path(self.temp.name)/'survey.sqlite3'),
                         ALLOWED_HOSTS={'localhost'},ALLOW_ADMIN_SETUP=True,PUBLIC_URL='',SECURE_COOKIE=False)
        self.app=create_app(self.config);self.client=self.app.test_client()
        self.client.post('/api/auth/setup',json=dict(username='test-admin',password='Test-Only-Password-2026'))
        self.body=dict(id=str(uuid.uuid4()),name='研修アンケート',schema=dict(intro='研修のご感想',questions=[
            dict(title='満足度',type='scale',required=True),dict(title='感想',type='text',required=False)]))

    def test_register_update_snapshot_restart_backup(self):
        created=self.client.post('/api/admin/templates',json=self.body)
        self.assertEqual(created.status_code,201)
        self.assertEqual(self.client.post('/api/admin/templates',json=self.body).status_code,200)
        template=next(t for t in self.client.get('/api/admin/templates').json['templates'] if t['id']==self.body['id'])
        sid=str(uuid.uuid4())
        event=dict(id=sid,title='研修テスト',start='2026-11-17',schema=template['schema'])
        self.assertEqual(self.client.post('/api/admin/surveys',json=event).status_code,201)
        self.assertEqual(self.client.post('/api/responses',json=dict(id=str(uuid.uuid4()),survey_id=sid,name='テスト 太郎',answers={'q1':5})).status_code,201)
        before=self.client.get('/api/schema?survey='+sid).json['schema']
        edited=copy.deepcopy(self.body);edited.update(revision=1,name='研修アンケート 改訂')
        edited['schema']['questions'][0]['title']='改訂後の質問'
        edited['schema']['questions'][1]['required']=True
        result=self.client.post('/api/admin/templates/update',json=edited)
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['revision'],2)
        self.assertEqual(self.client.post('/api/admin/templates/update',json=edited).json['revision'],2)
        self.assertEqual(self.client.get('/api/schema?survey='+sid).json['schema'],before)
        data=self.client.get('/api/admin/data?survey='+sid).json
        self.assertEqual(data['summary']['total'],1);self.assertEqual(data['responses'][0]['answers'],{'q1':5})
        export=self.client.get('/api/admin/export?survey='+sid)
        self.assertEqual(export.status_code,200)
        self.assertEqual(load_workbook(io.BytesIO(export.data))['設問一覧']['C5'].value,'満足度')
        restarted=create_app(self.config).test_client()
        restarted.post('/api/auth/login',json=dict(username='test-admin',password='Test-Only-Password-2026'))
        saved=next(t for t in restarted.get('/api/admin/templates').json['templates'] if t['id']==self.body['id'])
        self.assertEqual(saved['revision'],2);self.assertTrue(saved['schema']['questions'][1]['required'])
        self.assertEqual(self.client.post('/api/admin/surveys',json={**event,'id':str(uuid.uuid4()),'schema':saved['schema']}).status_code,201)
        backup=Path(self.temp.name)/'backup.sqlite3';copy_database(Path(self.config['DATABASE']),backup)
        restored=create_app({**self.config,'DATABASE':str(backup)}).test_client()
        restored.post('/api/auth/login',json=dict(username='test-admin',password='Test-Only-Password-2026'))
        self.assertEqual(restored.get('/api/admin/templates').json,restarted.get('/api/admin/templates').json)

    def test_builtin_edits_survive_startup_and_conflicts(self):
        defaults=self.client.get('/api/admin/templates').json['templates']
        self.assertEqual([(t['name'],len(t['schema']['questions'])) for t in defaults],[('ワーケーション',16),('飲み会',5)])
        original=defaults[1];edited=copy.deepcopy(original)
        edited['schema']['intro']='変更した説明';edited['name']='飲み会・更新版'
        self.assertEqual(self.client.post('/api/admin/templates/update',json=edited).status_code,200)
        stale=copy.deepcopy(original);stale['schema']['intro']='別の画面の古い編集'
        self.assertEqual(self.client.post('/api/admin/templates/update',json=stale).status_code,409)
        restarted=create_app(self.config).test_client()
        restarted.post('/api/auth/login',json=dict(username='test-admin',password='Test-Only-Password-2026'))
        saved=restarted.get('/api/admin/templates').json['templates']
        self.assertEqual(len(saved),2);self.assertEqual(saved[1]['name'],'飲み会・更新版')
        self.assertEqual(saved[1]['schema']['intro'],'変更した説明')

    def test_permissions_duplicate_name_and_invalid_schema(self):
        anon=self.app.test_client()
        self.assertEqual(anon.get('/api/admin/templates').status_code,401)
        for path in ['/api/admin/templates','/api/admin/templates/update']:
            self.assertEqual(anon.post(path,json=self.body).status_code,401)
        self.assertEqual(self.client.post('/api/admin/templates',json=self.body).status_code,201)
        self.assertEqual(self.client.post('/api/admin/templates',json={**self.body,'id':str(uuid.uuid4()),'name':' 研修アンケート '}).status_code,409)
        for changes in [{'name':''},{'name':'x'*101},{'name':'a\nb'},{'schema':{'questions':[]}},{'id':'bad-id'}]:
            self.assertEqual(self.client.post('/api/admin/templates',json={**self.body,**changes}).status_code,400)
        self.assertEqual(self.client.post('/api/admin/templates/update',json={**self.body,'id':str(uuid.uuid4()),'name':'未登録','revision':1}).status_code,404)
        self.assertEqual(self.client.post('/api/admin/templates/update',json={**self.body,'revision':False}).status_code,400)
        builtin=self.client.get('/api/admin/templates').json['templates'][0]
        self.assertEqual(self.client.post('/api/admin/templates/update',json={**builtin,'name':self.body['name']}).status_code,409)


if __name__=='__main__': unittest.main()
