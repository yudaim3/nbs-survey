"""Run only after stopping the isolated test app; restore to a disposable path."""
from pathlib import Path
import sqlite3
import sys
import tempfile

sys.path.insert(0,'/app')
from data_transfer import copy_database
from webapp import create_app
import survey

source=Path('/data/survey.sqlite3')
with tempfile.TemporaryDirectory(prefix='nbs-restore-check-') as folder:
    backup=Path(folder)/'backup.sqlite3'
    restored=Path(folder)/'restored.sqlite3'
    copy_database(source,backup)
    copy_database(backup,restored)
    with sqlite3.connect(source) as original,sqlite3.connect(restored) as copy:
        for table in ('surveys','responses','categories','templates','admin_account'):
            assert original.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()==copy.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
    app=create_app({'DATABASE':str(restored)})
    with app.app_context():
        items=survey.list_surveys(admin=True)
        assert sum(s['response_count'] for s in items)>0
        assert survey.list_templates() and survey.list_categories()
        for item in items:
            survey.summarize(survey.snapshot(item['id']))
print('PASS: database backup restored to a separate temporary file; answers, categories, templates, admin and summaries verified.')
