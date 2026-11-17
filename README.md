# NBS SURVEY

カテゴリー別のアンケート作成、自由な設問設定、Web回答、集計、6シートのExcel出力を行うアプリです。
アプリの実行にCodex・Node.js・Excelのインストール・AI APIは不要です。
Python / Flask / Waitress / openpyxl / SQLiteで構成しています。

## カテゴリーとフォームの作成

1. 管理画面で「アンケート・ひな形を作成／編集」を開きます。
2. カテゴリー、開催名、開催日、場所を入力します。必要なカテゴリーがなければ絞り込み欄の横の「＋ 追加」で登録します。
3. 「アンケート・ひな形を作成／編集」で、空のフォームから質問を追加するか、保存済みのひな形を読み込みます。初期ひな形はワーケーション16問・飲み会5問です。
4. 質問文・回答形式・必須／任意を設定します。選択肢は1行に1つ入力します。
5. 必要に応じて質問を追加・削除・上下に並べ替え、「アンケートを作成」を押します。
6. 発行された回答用URLを共有します。管理画面と利用者一覧の両方でカテゴリーを絞り込めます。

回答形式：ラジオボタン、プルダウン、複数選択、1行入力、複数行入力、数値、日付、5段階評価、項目別評価、項目別の必要数。
カテゴリーは管理者のみ追加でき、名前は50文字以内です。前後の空白を除いた同名は重複登録しません。
初期カテゴリーはワーケーション・飲み会・その他です。追加したカテゴリーはDBに保存され、作成・開催情報編集・両一覧の絞り込みに反映されます。
追加直後は新しいアンケートのカテゴリーに選択されます。別タブで開いている利用者一覧は再読み込みしてください。
カテゴリー自体の削除・名称変更はありません。DB全体のバックアップには、まだアンケートで使っていないカテゴリーも含まれます。

### ひな形の新規登録・編集

同じ質問編集欄で、説明文・質問・回答形式・必須／任意・選択肢・順番を設定できます。
質問編集欄の下で「ひな形名」を入力し、「新しいひな形として登録」を押すと保存します。
既存ひな形の修正は、ひな形を選択して「ひな形を読み込む」→編集→「読み込んだひな形を更新」です。
初期のワーケーション・飲み会も編集できます。別名で新規登録すれば、元のひな形を残して複製できます。
ひな形だけの保存では、開催名・日付・場所は不要です。名前は100文字以内、同名の重複登録はできません。
ひな形を変更しても、作成済みアンケートの設問・回答・集計は変わりません。新しく作成するアンケートに読み込んで使います。
別の画面で更新済みの場合は、古い版での上書きを防止します。編集内容を別名で新規登録するか、ひな形を読み込み直してください。
ひな形はDBに保存され、サーバーの再起動やDB全体のバックアップ・復元で引き継がれます。削除機能はありません。
質問は1〜50問、選択肢は各1〜50件です。複数選択には最大選択数を指定できます。
選択肢に「その他」を入れると、選んだ方に補足入力が必要になります。
回答者名は引き続き必須です。利用者画面には必須項目のみ「必須」と表示します。

作成したアンケートの設問は固定です。変更した設問で実施する場合は新しいアンケートを作成してください。
カテゴリー・開催名・日付・場所・受付状態は作成後も変更できます。
既存のアンケートはワーケーションとして表示し、元の設問・回答・URL・集計方式を維持します。
設問はアンケートごとにDBへ保存され、ExcelとJSONバックアップにも含まれます。
新規フォームは共通の集計形式、既存ワーケーションは従来の専用集計形式で出力します。
表示名変更後もDockerのプロジェクト名・ボリューム名は `nbs-workation` のままです（保存済み回答を継続利用するため）。

ローカルの自動検証：`python tests/test_templates.py`、`python tests/test_custom_forms.py`、`python tests/test_portability.py`、`python tests/test_integration.py`。
Docker用の `test-docker.ps1` にもカテゴリー・カスタム設問・任意回答・再作成後の保持の検証を含めています。

## 今回の検証状況

- HTTP経由のログイン、回答登録、開催回別集計、Excel出力、サーバー再起動後の保持をテスト済み。
- 旧DBの移行、空回答時の出力、長い日本語・絵文字、数式として扱わない文字列出力をテスト済み。
- Composeファイルは公式JSON Schemaで検証済み。ベースイメージの存在も確認済み。
- **このWindows PCではDocker / WSLが未導入のため、Dockerのビルド・起動テストは未実施です。**
- 機能テストのPython本体には、このPCで利用可能な既存ランタイムを使用しています。Codex未導入PCでの実機確認はこれからです。
- AWSにはまだ配置していません。

## 別PCでの確認・本番用設定

初心者向けの手順は [別PCでのDocker確認手順.txt](別PCでのDocker確認手順.txt) にまとめています。
通常の画面確認は `start.cmd`、公開用HTTPS構成の自動テストは `test-publication.cmd` です。
新しい公開用構成のテストは、カテゴリー・ひな形・Excel・バックアップ復元・コンテナ再作成後の保持も確認します。
このPCではComposeの公式スキーマ・PowerShell/Python構文と、同じ確認コードのHTTP動作を検証しています。
Docker / Caddy / TLSの実行確認は、別PCでこれから行います。

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

本番用は `compose.production.yaml` 単独で起動します。通常の `compose.yaml` とは重ねません。
HTTPSを受け付けるCaddyと、外部へポートを公開しないアプリを組み合わせています。
`deploy/Caddyfile` は本番・HTTPSテストで共用します。テストだけ内部証明書を使い、テストクライアントは証明書を検証します。
本番では `SECURE_COOKIE=true`・`ALLOW_ADMIN_SETUP=false` を固定し、公開URLをドメインから設定します。
`.env.production.example` を `.env.production` にコピーして `DOMAIN` を設定します。空欄のままでは起動できません。
管理者初期登録、DNS、AWSの通信設定、起動コマンドは [AWS公開手順.txt](AWS公開手順.txt) を参照してください。
実際のドメインは未定、AWSは未設定です。公開用証明書取得・外部接続・定期バックアップはAWS側での確認と設定が残ります。
アプリは任意の転送ヘッダーを信頼しません。ログイン失敗の制限はプロキシ越しでは共有される場合があります。

## 構成とテスト

- `server.py`: Waitressの起動・管理者の初期登録
- `webapp.py`: Web/API、認証、公開URLとCookieの設定
- `survey.py`: SQLite、設問の検証、集計
- `excel_export.py`: 6シートのExcel生成（数値は出力時の確定値）
- `data_transfer.py`: DBの整合したコピー・初回移行
- `public/`: 画面、NBS SURVEYの名称、水色のデザイン
- `Dockerfile` / `compose.yaml`: コンテナのビルド、起動、永続保存
- `compose.production.yaml` / `deploy/Caddyfile`: EC2向けHTTPS構成
- `compose.https-test.yaml` / `test-publication.cmd`: 別PCで公開用構成を確認するテスト

```sh
python tests/test_integration.py
python tests/test_portability.py
```

実際の回答、管理者情報、ログ、依存ライブラリー、Excel、バックアップはGitやDockerイメージへ含めません。
参加者の本人確認や、同じ人の複数回回答の完全な防止は行いません。
集計ExcelをCodexに添付して報告書に整える運用は、引き続き可能です。
