#!/usr/bin/env python3
"""state/new_entries.json を読み、新着PDFのGitHubリンクをDiscordに通知する。

コミット・push後に実行すること(リンクが指す内容がリモートに存在している必要があるため)。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parent.parent
NEW_ENTRIES_PATH = ROOT / "state" / "new_entries.json"

REQUEST_TIMEOUT = 30
DISCORD_MESSAGE_LIMIT = 1900


def github_blob_url(repo_relative_path: str) -> str | None:
    server = os.environ.get("GITHUB_SERVER_URL")
    repo = os.environ.get("GITHUB_REPOSITORY")
    ref = os.environ.get("GITHUB_REF_NAME") or "main"
    if not server or not repo:
        return None
    quoted_path = "/".join(quote(part) for part in repo_relative_path.split("/"))
    return f"{server}/{repo}/blob/{ref}/{quoted_path}"


def build_message_lines(entries: list[dict]) -> list[str]:
    lines = []
    for e in entries:
        link = github_blob_url(e["path"])
        if link is None:
            link = f"(リンク生成不可: {e['path']})"
        lines.append(f"・[{e['target_name']}] {e['title']}\n  {link}")
    return lines


def send_discord(webhook_url: str, entries: list[dict]) -> None:
    header = f"気象庁の新着資料を{len(entries)}件検知しました\n"
    lines = build_message_lines(entries)

    chunk = header
    chunks = []
    for line in lines:
        if len(chunk) + len(line) + 1 > DISCORD_MESSAGE_LIMIT:
            chunks.append(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        chunks.append(chunk)

    session = requests.Session()
    for content in chunks:
        resp = session.post(webhook_url, json={"content": content}, timeout=REQUEST_TIMEOUT)
        if resp.status_code >= 300:
            print(f"Discord notification failed: {resp.status_code} {resp.text}", file=sys.stderr)


def main() -> int:
    if not NEW_ENTRIES_PATH.exists():
        print("新着PDFはありませんでした(通知なし)")
        return 0

    with open(NEW_ENTRIES_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    if not entries:
        print("新着PDFはありませんでした(通知なし)")
        NEW_ENTRIES_PATH.unlink(missing_ok=True)
        return 0

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set; skipping notification")
        return 0

    send_discord(webhook_url, entries)
    NEW_ENTRIES_PATH.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
