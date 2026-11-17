import io
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from openpyxl import load_workbook
from webapp import create_app
from data_transfer import copy_database
import survey


class PortabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.db = str(Path(self.temp.name) / 'survey.sqlite3')
        self.app = create_app({'TESTING': True, 'DATABASE': self.db, 'ALLOW_ADMIN_SETUP': True,
                               'ALLOWED_HOSTS': {'localhost'}, 'PUBLIC_URL': '', 'SECURE_COOKIE': False})
        self.client = self.app.test_client()
        self.sid = self.client.get('/api/surveys').json['surveys'][0]['id']

    def login(self):
        response = self.client.post('/api/auth/setup', json={'username': 'test-admin', 'password': 'Test-Only-Password-2026'})
        self.assertEqual(response.status_code, 200)

    def test_empty_export_and_literal_text(self):
        self.login()
        empty = self.client.get('/api/admin/export?survey=' + self.sid)
        book = load_workbook(io.BytesIO(empty.data), data_only=False)
        self.assertEqual(len(book.sheetnames), 6)
        self.assertEqual(book['集計サマリー']['B8'].value, 0)
        self.assertIsNone(book['集計サマリー']['B9'].value)
        text = '=HYPERLINK("https://example.invalid","test")\n' + '長文📝\n' * 900
        rid = str(uuid.uuid4())
        response = self.client.post('/api/responses', json={
            'id': rid, 'survey_id': self.sid, 'name': '=1+1', 'answers': {'q3': text, 'q12': {'トイレ': '6以上'}}, 'other': {}})
        self.assertEqual(response.status_code, 201)
        result = self.client.get('/api/admin/export?survey=' + self.sid)
        self.assertEqual(result.status_code, 200)
        book = load_workbook(io.BytesIO(result.data), data_only=False)
        rows = list(book['自由記述一覧'].iter_rows(min_row=5, values_only=True))
        self.assertEqual(''.join(r[6] for r in rows), text.strip())
        self.assertEqual(book['自由記述一覧']['B5'].value, '=1+1')
        self.assertEqual(book['自由記述一覧']['B5'].data_type, 's')
        self.assertTrue(all(cell.data_type != 'f' for sheet in book for row in sheet for cell in row))
        self.assertTrue(any(row[5] == '6以上' for row in book['回答データ'].iter_rows(min_row=5, values_only=True)))

    def test_host_origin_and_size_guards(self):
        self.assertEqual(self.client.get('/api/health', headers={'Host': 'evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/auth/setup', json={}, headers={'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/auth/setup', data='{}', content_type='text/plain').status_code, 415)
        self.assertEqual(self.client.post('/api/auth/setup', data='x' * 250001, content_type='application/json').status_code, 413)

    def test_https_login_and_disabled_bootstrap(self):
        self.login()
        app = create_app({'TESTING': True, 'DATABASE': self.db, 'ALLOW_ADMIN_SETUP': False,
                          'ALLOWED_HOSTS': {'survey.example'}, 'PUBLIC_URL': 'https://survey.example', 'SECURE_COOKIE': True})
        client = app.test_client()
        response = client.post('/api/auth/login', base_url='https://survey.example', headers={'Origin': 'https://survey.example'},
                               json={'username': 'test-admin', 'password': 'Test-Only-Password-2026'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertIn('HttpOnly', response.headers['Set-Cookie'])
        self.assertEqual(client.get('/api/admin/surveys', base_url='https://survey.example').status_code, 200)
        fresh = create_app({'TESTING': True, 'DATABASE': str(Path(self.temp.name) / 'new.sqlite3'),
                            'ALLOW_ADMIN_SETUP': False, 'ALLOWED_HOSTS': {'localhost'}, 'PUBLIC_URL': ''})
        self.assertEqual(fresh.test_client().post('/api/auth/setup', json={'username':'test-admin','password':'Test-Only-Password-2026'}).status_code, 403)

    def test_snapshot_migration_and_refuse_overwrite(self):
        self.login()
        target = Path(self.temp.name) / 'docker' / 'survey.sqlite3'
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertTrue(copy_database(self.db, target))
        with closing(sqlite3.connect(target)) as restored:
            self.assertEqual(restored.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(restored.execute('SELECT id FROM surveys').fetchone()[0], self.sid)
            self.assertEqual(restored.execute('SELECT username FROM admin_account').fetchone()[0], 'test-admin')
        before = target.read_bytes()
        self.assertFalse(copy_database(self.db, target, if_empty=True))
        self.assertEqual(target.read_bytes(), before)
        with self.assertRaises(FileExistsError):
            copy_database(self.db, target)

    def test_offline_import_includes_committed_wal(self):
        target = Path(self.temp.name) / 'docker' / 'with-wal.sqlite3'
        with closing(sqlite3.connect(self.db)) as source:
            source.execute('PRAGMA wal_autocheckpoint=0')
            source.execute('CREATE TABLE wal_check (value TEXT)')
            source.execute("INSERT INTO wal_check VALUES ('committed in WAL')")
            source.commit()
            self.assertTrue(Path(self.db + '-wal').exists())
            # The connection stays open to retain WAL, but no writer is active.
            copy_database(self.db, target, offline_source=True)
        with closing(sqlite3.connect(target)) as restored:
            self.assertEqual(restored.execute('SELECT value FROM wal_check').fetchone()[0], 'committed in WAL')


if __name__ == '__main__':
    unittest.main()
