# JMA-monitoring-material

気象庁の資料監視

指定した気象庁のページを毎日巡回し、新しい資料の公開を検知したらDiscordに通知します。監視方式は対象ごとに2種類あります。

- **PDF監視**(`type: pdf_list`): ページ内の新着PDFリンクを検知し、PDF本体をダウンロードしてリポジトリにコミットします。
- **発表検知**(`type: json_bulletin`): JSON APIの発表日時(reportDatetime)の変化を見て、新しい発表(季節予報など、ダウンロード可能なPDFが存在しないもの)を検知します。ファイルの保存は行わず、通知のみです。

## 構成

- `config/targets.yaml` — 監視対象のリスト。今後ここに追記していく想定。
- `scripts/monitor.py` — 監視を行う本体スクリプト。新着があれば `state/new_entries.json` に書き出す。
- `scripts/notify.py` — `state/new_entries.json` を読み、Discordに通知する(コミット・push後に実行する)。
- `state/downloaded.json` — (PDF監視用)既にダウンロード済みのPDF URL一覧(重複ダウンロード防止用)。
- `state/bulletins.json` — (発表検知用)対象ごとに最後に検知した発表日時(reportDatetime)。
- `downloads/<target id>/` — ダウンロードしたPDFの保存先(PDF監視のみ)。
- `.github/workflows/monitor.yml` — 毎日実行するGitHub Actionsワークフロー(手動実行も可能)。

## 監視対象の追加方法

`config/targets.yaml` に以下の形式で追記してください。

### PDF監視 (pdf_list)

```yaml
targets:
  - id: extreme_japan       # ダウンロード先フォルダ名やstateのキーにもなる一意なID
    type: pdf_list
    name: 日本の異常気象      # 通知メッセージ等での表示名
    url: https://www.data.jma.go.jp/cpd/longfcst/extreme_japan/index.html
```

対象ページ内の `.pdf` で終わるリンクをすべて新着候補として扱います。

### 発表検知 (json_bulletin)

気象庁の「統合地図ページ」(`bosai/map.html`)のようにJavaScriptでJSON APIから描画するページは、PDFへのリンクが存在しないため上記の方式では監視できません。その場合は、ページが参照しているJSON APIを直接監視します(`reportDatetime` フィールドの変化で新着判定)。

```yaml
targets:
  - id: season_1month
    type: json_bulletin
    name: 1か月予報(全国)
    url: https://www.jma.go.jp/bosai/season/data/P1M/010000.json   # 監視するJSON API
    web_url: "https://www.jma.go.jp/bosai/map.html#5/34.5/137/&elem=temperature&pattern=P1M&term=0&contents=season"  # 通知に載せる人間向けページ
```

JSON APIのURLは対象ページのHTML/JSを見て見つける必要があります(ブラウザの開発者ツールのNetworkタブで `.json` へのリクエストを探すのが手軽です)。

## Discord通知の設定

リポジトリの Settings > Secrets and variables > Actions で `DISCORD_WEBHOOK_URL` という名前のSecretにDiscordのWebhook URLを登録してください。未設定の場合、監視・保存・コミットは行われますが通知はスキップされます。

PDF監視のエントリはGitHub上のPDFへのリンク(例: `https://github.com/<owner>/<repo>/blob/main/downloads/<id>/xxx.pdf`)を、発表検知のエントリは対象ページの `web_url` をそのまま通知に掲載します。GitHubリンクはpush後でないと閲覧できないため、`notify.py` は必ずコミット・push後に実行してください(`.github/workflows/monitor.yml` はその順序で組んであります)。

## ローカルでの実行

```bash
pip install -r requirements.txt
python scripts/monitor.py
# 新着があれば state/new_entries.json ができる
# コミット・push後に通知する場合:
DISCORD_WEBHOOK_URL=... python scripts/notify.py
```

ローカル実行時は `GITHUB_REPOSITORY` / `GITHUB_SERVER_URL` 環境変数が無いため、`notify.py` はPDF監視エントリのGitHubリンクを生成できずその旨を表示します(GitHub Actions上では自動的に設定されます)。発表検知エントリの通知は `web_url` を使うため、この制約の影響を受けません。

## 動作の流れ

1. `config/targets.yaml` に記載された各対象を種類ごとにチェック
   - `pdf_list`: ページを取得しPDFリンクを抽出。`state/downloaded.json` に記録のないURL(=新着)のみダウンロードし、`downloads/<id>/` に保存
   - `json_bulletin`: JSON APIを取得し `reportDatetime` を `state/bulletins.json` の記録と比較。変化していれば新着として扱う
2. 新着があれば各stateファイルを更新し、`state/new_entries.json` に新着一覧を書き出す
3. GitHub Actions側で変更があればコミット・push
4. push後に `notify.py` が `state/new_entries.json` を読み、Discordに通知
