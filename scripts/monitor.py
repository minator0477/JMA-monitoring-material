#!/usr/bin/env python3
"""気象庁の監視対象ページを巡回し、新着PDFをダウンロードしてDiscordに通知する。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "targets.yaml"
STATE_PATH = ROOT / "state" / "downloaded.json"
DOWNLOADS_DIR = ROOT / "downloads"

USER_AGENT = (
    "Mozilla/5.0 (compatible; JMA-monitoring-bot/1.0; "
    "+https://github.com/)"
)
REQUEST_TIMEOUT = 30
DISCORD_MESSAGE_LIMIT = 1900


@dataclass
class PdfEntry:
    target_id: str
    target_name: str
    title: str
    url: str
    path: str
    downloaded_at: str


def load_targets() -> list[dict]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("targets", [])


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def extract_pdf_links(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen_urls: set[str] = set()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href.lower().split("?")[0].endswith(".pdf"):
            continue
        absolute_url = urljoin(page_url, href)
        if absolute_url in seen_urls:
            continue
        seen_urls.add(absolute_url)
        title = a.get_text(strip=True) or Path(urlparse(absolute_url).path).name
        links.append({"url": absolute_url, "title": title})
    return links


def download_pdf(session: requests.Session, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = session.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    dest.write_bytes(resp.content)


def notify_discord(new_entries: list[PdfEntry]) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        print("DISCORD_WEBHOOK_URL not set; skipping notification")
        return

    header = f"気象庁の新着資料を{len(new_entries)}件検知しました\n"
    lines = [
        f"・[{e.target_name}] {e.title}\n  {e.url}" for e in new_entries
    ]

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
    targets = load_targets()
    state = load_state()
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    new_entries: list[PdfEntry] = []

    for target in targets:
        target_id = target["id"]
        target_name = target.get("name", target_id)
        url = target["url"]

        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[{target_id}] ページ取得に失敗しました: {e}", file=sys.stderr)
            continue

        resp.encoding = resp.apparent_encoding or resp.encoding
        pdf_links = extract_pdf_links(resp.text, url)
        print(f"[{target_id}] {len(pdf_links)}件のPDFリンクを検出")

        for link in pdf_links:
            pdf_url = link["url"]
            if pdf_url in state:
                continue

            filename = Path(urlparse(pdf_url).path).name
            dest = DOWNLOADS_DIR / target_id / filename

            try:
                download_pdf(session, pdf_url, dest)
            except requests.RequestException as e:
                print(f"[{target_id}] ダウンロード失敗 {pdf_url}: {e}", file=sys.stderr)
                continue

            entry = PdfEntry(
                target_id=target_id,
                target_name=target_name,
                title=link["title"],
                url=pdf_url,
                path=str(dest.relative_to(ROOT)),
                downloaded_at=datetime.now(timezone.utc).isoformat(),
            )
            state[pdf_url] = asdict(entry)
            new_entries.append(entry)
            print(f"[{target_id}] 新規ダウンロード: {pdf_url}")

    if new_entries:
        save_state(state)
        notify_discord(new_entries)
    else:
        print("新着PDFはありませんでした")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
