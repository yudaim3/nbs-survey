"""Consistent SQLite backup/import. Never overwrite an existing database."""
import argparse
from contextlib import closing, contextmanager
import os
from pathlib import Path
import sqlite3
import shutil
import tempfile


@contextmanager
def readable_source(source, offline):
    if not offline:
        yield source
        return
    # Caller has stopped all source writers. Copy DB + committed WAL to a writable
    # staging directory so SQLite can recover WAL even from a read-only Docker mount.
    with tempfile.TemporaryDirectory(prefix='nbs-import-') as directory:
        staged = Path(directory) / 'survey.sqlite3'
        shutil.copyfile(source, staged)
        wal = Path(str(source) + '-wal')
        if wal.exists():
            shutil.copyfile(wal, Path(str(staged) + '-wal'))
        yield staged


def copy_database(source, target, if_empty=False, offline_source=False):
    source, target = Path(source).resolve(), Path(target).resolve()
    if target.exists():
        if if_empty:
            print('Destination already exists; kept its data unchanged.')
            return False
        raise FileExistsError('Destination already exists; choose a new backup file.')
    if not source.is_file():
        raise FileNotFoundError('Source database was not found.')
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix='.sqlite-backup-', dir=target.parent)
    os.close(handle)
    try:
        with readable_source(source, offline_source) as readable, closing(sqlite3.connect(readable.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(temporary)) as dest:
                src.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Database integrity check failed.')
                tables = {r[0] for r in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'responses', 'settings'} <= tables:
                    raise ValueError('This is not an NBS WORKATION database.')
                # The copied file must stand alone; no source WAL files are needed.
                dest.execute('PRAGMA journal_mode=DELETE')
        # Exclusive creation prevents accidental replacement, including concurrent imports.
        os.link(temporary, target)
        print('Database copied successfully. Source unchanged.')
        return True
    finally:
        Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('target')
    parser.add_argument('--if-empty', action='store_true')
    parser.add_argument('--offline-source', action='store_true', help='Only use after stopping all source writers')
    args = parser.parse_args()
    copy_database(args.source, args.target, args.if_empty, args.offline_source)
