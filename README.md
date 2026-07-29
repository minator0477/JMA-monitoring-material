# JMA-monitoring-material

気象庁の資料監視

指定した気象庁のページを毎日巡回し、新しく公開されたPDF資料を検知したら自動でダウンロードしてリポジトリにコミットします。新着があればDiscordに通知します。

## 構成

- `config/targets.yaml` — 監視対象ページのリスト。今後ここに追記していく想定。
- `scripts/monitor.py` — 監視・ダウンロード・Markdown変換を行う本体スクリプト。新着があれば `state/new_entries.json` に書き出す。
- `scripts/notify.py` — `state/new_entries.json` を読み、Discordに通知する(コミット・push後に実行する)。
- `state/downloaded.json` — 既にダウンロード済みのPDF URL一覧(重複ダウンロード防止用)。
- `downloads/<target id>/` — ダウンロードしたPDFと、その内容をテキスト化したMarkdown(同名の`.md`)の保存先。
- `.github/workflows/monitor.yml` — 毎日実行するGitHub Actionsワークフロー(手動実行も可能)。

## 監視対象の追加方法

`config/targets.yaml` に以下の形式で追記してください。

```yaml
targets:
  - id: extreme_japan       # ダウンロード先フォルダ名にもなる一意なID
    name: 日本の異常気象      # 通知メッセージ等での表示名
    url: https://www.data.jma.go.jp/cpd/longfcst/extreme_japan/index.html
```

対象ページ内の `.pdf` で終わるリンクをすべて新着候補として扱います。

## Discord通知の設定

リポジトリの Settings > Secrets and variables > Actions で `DISCORD_WEBHOOK_URL` という名前のSecretにDiscordのWebhook URLを登録してください。未設定の場合、ダウンロードとコミットは行われますが通知はスキップされます。

通知にはGitHub上のMarkdownファイルへのリンク(例: `https://github.com/<owner>/<repo>/blob/main/downloads/<id>/xxx.md`)を掲載します。このリンクはpush後でないと閲覧できないため、`notify.py` は必ずコミット・push後に実行してください(`.github/workflows/monitor.yml` はその順序で組んであります)。

## ローカルでの実行

```bash
pip install -r requirements.txt
python scripts/monitor.py
# 新着があれば state/new_entries.json ができる
# コミット・push後に通知する場合:
DISCORD_WEBHOOK_URL=... python scripts/notify.py
```

ローカル実行時は `GITHUB_REPOSITORY` / `GITHUB_SERVER_URL` 環境変数が無いため、`notify.py` はGitHubリンクを生成できずその旨を表示します(GitHub Actions上では自動的に設定されます)。

## 動作の流れ

1. `config/targets.yaml` に記載された各ページを取得
2. ページ内のPDFリンクを抽出
3. `state/downloaded.json` に記録のないURL(=新着)のみダウンロードし、`downloads/<id>/` に保存(併せてMarkdownにも変換して保存)
4. 新着があれば `state/downloaded.json` を更新し、`state/new_entries.json` に新着一覧を書き出す
5. GitHub Actions側で変更があればコミット・push
6. push後に `notify.py` が `state/new_entries.json` を読み、GitHub上のMarkdownへのリンクをDiscordに通知
