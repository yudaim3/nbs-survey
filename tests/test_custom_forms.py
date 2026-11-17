"""End-to-end API contracts for custom forms, existing surveys, and Excel exports."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from webapp import create_app
import survey


class CustomFormsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = dict(TESTING=True, DATABASE=str(Path(self.temp.name)/'test.sqlite3'),
                           ALLOWED_HOSTS={'localhost'}, ALLOW_ADMIN_SETUP=True, PUBLIC_URL='', SECURE_COOKIE=False)
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.client.post('/api/auth/setup', json=dict(username='test-admin', password='Test-Only-Password-2026'))
        self.definition = {'intro': 'テスト用の説明', 'questions': [
            dict(title='参加したいですか', type='single', required=True, options=['はい', 'いいえ']),
            dict(title='希望会場', type='select', required=False, options=['会場A', 'その他']),
            dict(title='希望料理', type='multi', required=True, options=['和食', '洋食', '特になし'], max=2),
            dict(title='部署', type='shorttext', required=False),
            dict(title='感想', type='text', required=False),
            dict(title='金額', type='number', required=True),
            dict(title='希望日', type='date', required=True),
            dict(title='満足度', type='scale', required=True),
            dict(title='項目別評価', type='rating', required=False, options=['料理', '会場']),
            dict(title='必要数', type='count', required=True, options=['テーブル']),
        ]}
        self.body = dict(id=str(uuid.uuid4()), title='飲み会テスト', start='2026-11-20', end='', place='テスト会場', category='飲み会', schema=self.definition)
        response = self.client.post('/api/admin/surveys', json=self.body)
        self.assertEqual(response.status_code, 201, response.json)
        self.sid = response.json['id']
        self.answers = dict(q1='はい', q3=['和食'], q6=0, q7='2026-11-21', q8=4, q10={'テーブル': '6以上'})

    def submit(self, answers=None, other=None):
        return self.client.post('/api/responses', json=dict(id=str(uuid.uuid4()), survey_id=self.sid,
                                name='テスト 太郎', answers=self.answers if answers is None else answers, other=other or {}))

    def test_categories_retry_and_restart(self):
        self.assertEqual(self.client.post('/api/admin/surveys', json=self.body).status_code, 200)
        changed=copy.deepcopy(self.body);changed['schema']['questions'][0]['required']=False
        self.assertEqual(self.client.post('/api/admin/surveys', json=changed).status_code, 409)
        for path in ['/api/surveys', '/api/admin/surveys']:
            items=self.client.get(path+'?category=飲み会').json['surveys']
            self.assertEqual([s['id'] for s in items], [self.sid])
            original=self.client.get(path+'?category=ワーケーション').json['surveys']
            self.assertEqual(len(original), 1)
            self.assertNotEqual(original[0]['id'], self.sid)
        self.assertEqual(self.submit().status_code, 201)
        restarted=create_app(self.config)
        with restarted.app_context():
            data=survey.snapshot(self.sid)
            self.assertEqual(len(data['responses']), 1)
            self.assertEqual(data['responses'][0]['answers']['q6'], 0)
            self.assertEqual(data['event']['category'], '飲み会')
            self.assertFalse(data['schema']['questions'][1]['required'])
        anon=self.app.test_client()
        self.assertEqual(anon.post('/api/admin/surveys', json=self.body).status_code, 401)
        self.assertEqual(anon.get('/api/admin/template').status_code, 401)
        self.assertEqual(len(self.client.get('/api/admin/template').json['schema']['questions']), 16)

    def test_optional_blank_required_and_types(self):
        valid={**self.answers, 'q2':'', 'q4':'   ', 'q5':'', 'q9':{}}
        self.assertEqual(self.submit(valid).status_code, 201)
        for key in self.answers:
            answers=copy.deepcopy(self.answers);del answers[key]
            with self.subTest(missing=key): self.assertEqual(self.submit(answers).status_code,400)
        for key,value in [('q1','不明'),('q2','不明'),('q3',['和食','特になし']),('q3',['和食','和食']),
                          ('q4','x'*301),('q5','x'*5001),('q6',True),('q6','100'),('q6',1e13),('q6',10**400),
                          ('q7','2026-02-30'),('q7','2026-1-1'),('q8',6),('q8',2.5),
                          ('q9',{'料理':'6'}),('q10',{})]:
            with self.subTest(key=key,value=str(value)[:30]):
                self.assertEqual(self.submit({**self.answers,key:value}).status_code,400)
        self.assertEqual(self.submit({**self.answers,'q2':'その他'}).status_code,400)
        self.assertEqual(self.submit({**self.answers,'q2':'その他'}, {'q2':'公園'}).status_code,201)
        self.assertEqual(self.submit({**self.answers,'q9':{'料理':'5'}}).status_code,201)
        self.assertEqual(self.submit({**self.answers,'q5':'その他'}).status_code,201)

    def test_aggregates_and_excel_every_type(self):
        first={**self.answers,'q2':'その他','q4':'=1+1','q5':'感想の原文','q9':{'料理':'5'}}
        self.assertEqual(self.submit(first,{'q2':'別の会場'}).status_code,201)
        self.assertEqual(self.submit({**self.answers,'q6':100,'q8':2}).status_code,201)
        data=self.client.get('/api/admin/data?survey='+self.sid).json
        stats=data['summary']['questions']
        self.assertEqual(stats['q6']['average'],50)
        self.assertEqual(stats['q8']['average'],3)
        self.assertEqual(stats['q2']['missing'],1)
        self.assertEqual(stats['q9']['rows'][1]['missing'],2)
        response=self.client.get('/api/admin/export?survey='+self.sid)
        self.assertEqual(response.status_code,200)
        book=load_workbook(io.BytesIO(response.data))
        raw=list(book['回答データ'].iter_rows(min_row=5,values_only=True))
        self.assertEqual({r[3] for r in raw},{f'Q{i}' for i in range(1,11)})
        self.assertTrue(any(r[3]=='Q6' and r[5]==0 for r in raw))
        self.assertTrue(any(r[3]=='Q10' and r[5]=='6以上' for r in raw))
        self.assertTrue(any(r[3]=='Q4' and r[5]=='=1+1' for r in raw))
        self.assertTrue(all(c.data_type!='f' for ws in book for row in ws for c in row))
        text=list(book['自由記述一覧'].iter_rows(min_row=5,values_only=True))
        self.assertTrue(any(r[6]=='別の会場' for r in text))
        definition=list(book['設問一覧'].iter_rows(min_row=5,values_only=True))
        self.assertEqual(definition[1][5], '任意')

    def test_invalid_definitions_and_empty_export(self):
        bad=[{}, {'questions':[]}, {'questions':[{'title':'質問','type':'script'}]},
             {'questions':[dict(title=' ',type='text')]},
             {'questions':[dict(title='質問',type='text',required='false')]},
             {'questions':[dict(title='質問',type='select',options=['a',' a '])]},
             {'questions':[dict(title='質問',type='multi',options=['a'],max=2)]},
             {'questions':[dict(title='質問',type='text')]*51}]
        for definition in bad:
            with self.subTest(definition=str(definition)[:80]):
                response=self.client.post('/api/admin/surveys',json={**self.body,'id':str(uuid.uuid4()),'schema':definition})
                self.assertEqual(response.status_code,400)
        export=self.client.get('/api/admin/export?survey='+self.sid)
        self.assertEqual(export.status_code,200)
        self.assertEqual(len(load_workbook(io.BytesIO(export.data)).sheetnames),6)
        self.assertEqual(self.client.post('/api/admin/surveys',json={**self.body,'id':str(uuid.uuid4()),'category':'不明'}).status_code,400)

    def test_add_category_use_filter_and_persist(self):
        anon = self.app.test_client()
        self.assertEqual(anon.post('/api/admin/categories',json={'name':'研修'}).status_code,401)
        added = self.client.post('/api/admin/categories',json={'name':'  研修  '})
        self.assertEqual(added.status_code,201)
        self.assertEqual(added.json['name'],'研修')
        duplicate = self.client.post('/api/admin/categories',json={'name':'研修'})
        self.assertEqual(duplicate.status_code,200)
        self.assertFalse(duplicate.json['created'])
        self.assertEqual(duplicate.json['categories'].count('研修'),1)
        body={**self.body,'id':str(uuid.uuid4()),'category':'研修'}
        self.assertEqual(self.client.post('/api/admin/surveys',json=body).status_code,201)
        for path in ['/api/surveys','/api/admin/surveys']:
            result=self.client.get(path+'?category=研修').json
            self.assertEqual([item['id'] for item in result['surveys']],[body['id']])
            self.assertIn('研修',result['categories'])
        self.assertEqual(self.client.post('/api/admin/event',json={**self.body,'survey_id':self.sid,'category':'研修'}).status_code,200)
        self.assertEqual(self.client.get('/api/schema?survey='+self.sid).json['event']['category'],'研修')
        restarted=create_app(self.config)
        self.assertEqual(restarted.test_client().get('/api/categories').json['categories'],added.json['categories'])
        from data_transfer import copy_database
        backup=Path(self.temp.name)/'category-backup.sqlite3'
        copy_database(Path(self.config['DATABASE']),backup)
        restored=create_app({**self.config,'DATABASE':str(backup)})
        self.assertIn('研修',restored.test_client().get('/api/categories').json['categories'])
        self.assertEqual(restored.test_client().get('/api/schema?survey='+body['id']).json['event']['category'],'研修')

    def test_category_validation_and_migration(self):
        for value in [None,'','   ',[],123,'a'*51,'研修\nイベント']:
            with self.subTest(name=value):
                self.assertEqual(self.client.post('/api/admin/categories',json={'name':value}).status_code,400)
        special='<研修&交流>'
        self.assertEqual(self.client.post('/api/admin/categories',json={'name':special}).status_code,201)
        self.assertIn(special,self.client.get('/api/categories').json['categories'])
        self.assertEqual(self.submit().status_code,201)
        with self.app.app_context(),survey.connect() as c:
            # Simulate a database from before category registration existed.
            event={**self.body,'category':'以前のカテゴリー'}
            c.execute('UPDATE surveys SET event=? WHERE id=?',(json.dumps(event,ensure_ascii=False),self.sid))
            c.execute('DROP TABLE categories')
        upgraded=create_app(self.config)
        categories=upgraded.test_client().get('/api/categories').json['categories']
        self.assertEqual(categories[:3],survey.CATEGORIES)
        self.assertIn('以前のカテゴリー',categories)
        with upgraded.app_context():
            self.assertEqual(len(survey.snapshot(self.sid)['responses']),1)


if __name__=='__main__': unittest.main()
