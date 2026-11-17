"""Start NBS WORKATION with Python, without Codex or Node.js."""
import argparse
import getpass
import logging
import os
from pathlib import Path
from waitress import serve
from webapp import create_app, create_admin
import survey


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', '8765')))
    parser.add_argument('--host', default=os.environ.get('BIND_HOST', '127.0.0.1'))
    parser.add_argument('--data-dir', default=os.environ.get('DATA_DIR', str(Path(__file__).resolve().parent / 'data')))
    parser.add_argument('--create-admin', action='store_true')
    args = parser.parse_args()
    os.environ['PORT'] = str(args.port)
    app = create_app({'DATABASE': str(Path(args.data_dir) / 'survey.sqlite3')})
    if args.create_admin:
        with app.app_context(), survey.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute('SELECT 1 FROM admin_account').fetchone():
                raise SystemExit('管理者は設定済みです。既存アカウントでログインしてください。')
            username = input('管理者ID: ').strip()
            password = getpass.getpass('パスワード（12〜128文字）: ')
            if password != getpass.getpass('パスワード（確認）: '):
                raise SystemExit('パスワードが一致しません。')
            create_admin(c, username, password)
        print('管理者を設定しました。')
        return
    logging.basicConfig(level=logging.INFO)
    print(f'NBS WORKATION: http://localhost:{args.port}/admin', flush=True)
    serve(app, host=args.host, port=args.port, threads=8,
          max_request_body_size=250000, channel_timeout=60, clear_untrusted_proxy_headers=True)


if __name__ == '__main__':
    main()
