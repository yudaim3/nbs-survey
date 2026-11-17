# NBS WORKATION

開催回ごとのアンケート作成、Web回答、集計、6シートのExcel出力を行うアプリです。
アプリの実行にCodex・Node.js・Excelのインストール・AI APIは不要です。
Python / Flask / Waitress / openpyxl / SQLiteで構成しています。

## 今回の検証状況

- HTTP経由のログイン、回答登録、開催回別集計、Excel出力、サーバー再起動後の保持をテスト済み。
- 旧DBの移行、空回答時の出力、長い日本語・絵文字、数式として扱わない文字列出力をテスト済み。
- Composeファイルは公式JSON Schemaで検証済み。ベースイメージの存在も確認済み。
- **このWindows PCではDocker / WSLが未導入のため、Dockerのビルド・起動テストは未実施です。**
- 機能テストのPython本体には、このPCで利用可能な既存ランタイムを使用しています。Codex未導入PCでの実機確認はこれからです。
- AWSにはまだ配置していません。

## WindowsでDockerを使って起動

まず [Docker導入手順.txt](Docker導入手順.txt) を参照してください。
Docker Desktopを起動し、エンジンが動作している状態で `start.cmd` をダブルクリックします。
管理画面は通常 `http://localhost:8765/admin`、参加者一覧は `http://localhost:8765/` です。
停止は `stop.cmd`。停止してもDockerの保存領域にある回答は残ります。

`start.cmd` は次を行います。

1. Dockerの起動状態と設定を確認し、イメージをビルドします。
2. このフォルダーの `server.pid` で管理している従来のPythonサーバーを停止します。
3. ローカルの `data/survey.sqlite3` が存在し、Docker側にDBがない場合のみ、DBとWALを安全なコピーから読み取り移行します。
4. Docker版を起動し、正常性を確認して管理画面を開きます。

別の方法で同じローカルDBを使用するサーバーを起動している場合は、移行前に停止してください。
移行元のDBは変更しません。開催回のID、回答、管理者の設定を引き継ぎます。
Docker側にDBがある場合は上書きせず、Docker側のデータを使います。
移行後の回答はDocker側だけに保存され、元の `data/` とは同期しません。

### Dockerの確認用テスト

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\test-docker.ps1
```

本番データとは別の `nbs-workation-check` プロジェクトを作り、回答・ログイン・Excelを検証します。
コンテナを削除して作り直した後にも回答と管理者設定が残ることを確認します。
最後にテスト用コンテナを停止・削除しますが、テスト専用ボリュームは残します。

## Dockerの基本操作（Windows / Linux共通）

ローカルデータの自動移行が不要な、新規環境向けのコマンドです。

```sh
docker compose up -d --build --wait
docker compose logs --tail 50 app
docker compose stop
```

デフォルトは `127.0.0.1:8765` のみで待ち受けます。インターネットには公開しません。
初回は管理画面で管理者ID・パスワードを設定できます。
必要なら `.env.example` を `.env` にコピーしてポートなどを変更します。

## Dockerを使わずPythonで起動

Python 3.12以上を別途インストールします。Windowsでは `start-python.cmd` で仮想環境と必要なパッケージを準備して起動します。
終了は `stop-python.cmd` です。Docker版とは同時に同じポートで起動しないでください。

Linuxなどで手動起動する場合：

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
ALLOW_ADMIN_SETUP=true python server.py
```

`ALLOW_ADMIN_SETUP=true` は、ローカル初回設定用です。
既存の管理者を上書きすることはできません。

## データとバックアップ

Docker版は名前付きボリューム `nbs-workation_survey-data` の `/data/survey.sqlite3` に保存します。
Python版は、このフォルダーの `data/survey.sqlite3` に保存します。
アプリの更新・通常のコンテナ作り直しでDockerのボリュームは消えません。
**`docker compose down -v` やDockerのボリューム削除は、回答を削除する操作です。実行しないでください。**

Docker版のDB全体のバックアップ：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\backup-docker.ps1
```

SQLiteのバックアップ機能を使い、稼働中でも整合したコピーを `backups/` に保存します。
このファイルには回答と管理者の認証情報が含まれます。社内の適切な別保存先にもコピーしてください。
管理画面のJSON出力は選択した開催回の回答用であり、管理者設定を含むDB全体のバックアップとは異なります。

## AWSへ配置する前の設定

このリポジトリはコンテナ用コードを含みますが、AWSへの公開設定は別途必要です。

- HTTPSを受け付けるリバースプロキシを用意し、Hostを保持してアプリへ転送する。
- `PUBLIC_URL=https://実際のドメイン`、`SECURE_COOKIE=true`、`ALLOW_ADMIN_SETUP=false` を設定する。
- 公開前に管理者を用意する。新規DBなら `docker compose run --rm app python server.py --create-admin` で対話入力する。
- 必要な通信だけを許可し、アプリのHTTPポートを直接インターネットに公開しない。
- 永続ディスク、別保存先への定期バックアップ、復元手順を用意する。
- 公開URLでログイン・回答・Excel・HTTPSの実機確認を行う。

同じEC2上のプロキシから転送する場合、現在のloopbackへのポート公開を利用できます。
別コンテナのプロキシから転送する場合はネットワーク設定を合わせます。
アプリは任意の転送ヘッダーを信頼しません。ログイン失敗の制限は接続元IP単位なので、プロキシ越しでは共有される場合があります。

## 構成とテスト

- `server.py`: Waitressの起動・管理者の初期登録
- `webapp.py`: Web/API、認証、公開URLとCookieの設定
- `survey.py`: SQLite、設問の検証、集計
- `excel_export.py`: 6シートのExcel生成（数値は出力時の確定値）
- `data_transfer.py`: DBの整合したコピー・初回移行
- `public/`: 画面、NBS WORKATIONの名称、水色のデザイン
- `Dockerfile` / `compose.yaml`: コンテナのビルド、起動、永続保存

```sh
python tests/test_integration.py
python tests/test_portability.py
```

実際の回答、管理者情報、ログ、依存ライブラリー、Excel、バックアップはGitやDockerイメージへ含めません。
参加者の本人確認や、同じ人の複数回回答の完全な防止は行いません。
集計ExcelをCodexに添付して報告書に整える運用は、引き続き可能です。
