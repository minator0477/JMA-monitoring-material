#!/usr/bin/env python3
"""気象庁の監視対象ページを巡回し、新着資料を検知する。

対応する監視方式(targetの type):
  pdf_list      … ページ内の <a href="*.pdf"> を新着PDFとして検知し、ダウンロードする
  json_bulletin … JSON APIの reportDatetime の変化で新しい発表を検知する(ダウンロードはしない)

Discordへの通知は行わない(コミット・push後にnotify.pyが行う)。
新着があった場合は state/new_entries.json に一覧を書き出す。
"""

from __future__ import annotations

import json
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
BULLETIN_STATE_PATH = ROOT / "state" / "bulletins.json"
NEW_ENTRIES_PATH = ROOT / "state" / "new_entries.json"
DOWNLOADS_DIR = ROOT / "downloads"

USER_AGENT = (
    "Mozilla/5.0 (compatible; JMA-monitoring-bot/1.0; "
    "+https://github.com/)"
)
REQUEST_TIMEOUT = 30


@dataclass
class Entry:
    target_id: str
    target_name: str
    title: str
    url: str
    path: str | None
    downloaded_at: str


def load_targets() -> list[dict]:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("targets", [])


def load_json_state(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_json_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
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


def check_pdf_list(target: dict, session: requests.Session, state: dict) -> list[Entry]:
    target_id = target["id"]
    target_name = target.get("name", target_id)
    url = target["url"]

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[{target_id}] ページ取得に失敗しました: {e}", file=sys.stderr)
        return []

    resp.encoding = resp.apparent_encoding or resp.encoding
    pdf_links = extract_pdf_links(resp.text, url)
    print(f"[{target_id}] {len(pdf_links)}件のPDFリンクを検出")

    entries = []
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

        entry = Entry(
            target_id=target_id,
            target_name=target_name,
            title=link["title"],
            url=pdf_url,
            path=str(dest.relative_to(ROOT)),
            downloaded_at=datetime.now(timezone.utc).isoformat(),
        )
        state[pdf_url] = asdict(entry)
        entries.append(entry)
        print(f"[{target_id}] 新規ダウンロード: {pdf_url}")

    return entries


def check_json_bulletin(target: dict, session: requests.Session, bulletin_state: dict) -> list[Entry]:
    target_id = target["id"]
    target_name = target.get("name", target_id)
    url = target["url"]
    web_url = target.get("web_url", url)

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[{target_id}] 取得/パースに失敗しました: {e}", file=sys.stderr)
        return []

    report_datetime = data.get("reportDatetime")
    if not report_datetime:
        print(f"[{target_id}] reportDatetimeが見つかりません", file=sys.stderr)
        return []

    last_seen = bulletin_state.get(target_id, {}).get("reportDatetime")
    if report_datetime == last_seen:
        print(f"[{target_id}] 更新なし (reportDatetime={report_datetime})")
        return []

    headline = (data.get("headlineText") or "").strip() or "新しい予報が発表されました"
    now = datetime.now(timezone.utc).isoformat()

    entry = Entry(
        target_id=target_id,
        target_name=target_name,
        title=headline,
        url=web_url,
        path=None,
        downloaded_at=now,
    )
    bulletin_state[target_id] = {"reportDatetime": report_datetime, "checked_at": now}
    print(f"[{target_id}] 新しい発表を検知: reportDatetime={report_datetime}")
    return [entry]


def main() -> int:
    targets = load_targets()
    state = load_json_state(STATE_PATH)
    bulletin_state = load_json_state(BULLETIN_STATE_PATH)
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    new_entries: list[Entry] = []
    state_changed = False
    bulletin_state_changed = False

    for target in targets:
        target_type = target.get("type", "pdf_list")

        if target_type == "pdf_list":
            entries = check_pdf_list(target, session, state)
            if entries:
                state_changed = True
        elif target_type == "json_bulletin":
            entries = check_json_bulletin(target, session, bulletin_state)
            if entries:
                bulletin_state_changed = True
        else:
            print(f"[{target.get('id')}] 未知のtype: {target_type}", file=sys.stderr)
            continue

        new_entries.extend(entries)

    if state_changed:
        save_json_state(STATE_PATH, state)
    if bulletin_state_changed:
        save_json_state(BULLETIN_STATE_PATH, bulletin_state)

    if new_entries:
        NEW_ENTRIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(NEW_ENTRIES_PATH, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in new_entries], f, ensure_ascii=False, indent=2)
            f.write("\n")
    else:
        print("新着はありませんでした")
        NEW_ENTRIES_PATH.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
