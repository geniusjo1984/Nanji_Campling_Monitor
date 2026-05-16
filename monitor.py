from __future__ import annotations

import argparse
import copy
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_URL = "https://yeyak.seoul.go.kr"
STATE_VERSION = 1
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SeoulCampingMonitor/1.0; "
        "+https://github.com/)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.5,en;q=0.3",
}


@dataclass(frozen=True)
class ServiceTarget:
    target_id: str
    label: str = ""
    url: str = ""

    @property
    def detail_url(self) -> str:
        return self.url or detail_url_for(self.target_id)


@dataclass(frozen=True)
class SearchCard:
    target_id: str
    title: str
    status: str
    url: str


@dataclass(frozen=True)
class ServiceSnapshot:
    target_id: str
    title: str
    status: str
    action: str
    available: bool
    url: str


def detail_url_for(target_id: str) -> str:
    return f"{BASE_URL}/web/reservation/selectReservView.do?rsv_svc_id={target_id}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def first_raw(text: str, pattern: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1) if match else ""


def first_text(text: str, pattern: str) -> str:
    return clean_text(first_raw(text, pattern))


def extract_detail_section(page_html: str) -> str:
    section = first_raw(
        page_html,
        r'(<div\s+class=["\']dt_top_box["\'][\s\S]*?</div>\s*<!--\s*//dt_top_box\s*-->)',
    )
    return section or page_html


def parse_detail_page(page_html: str, target: ServiceTarget) -> ServiceSnapshot:
    section = extract_detail_section(page_html)
    title = first_text(section, r'<span\s+class=["\']tit["\']>([\s\S]*?)</span>')
    status = first_text(section, r'<span\s+class=["\']bd_label\s+status\d+["\']>([\s\S]*?)</span>')

    button_box = first_raw(section, r'<div\s+class=["\']common_btn_box["\']>([\s\S]*?)(?:</div>|$)')
    actions = [
        clean_text(match)
        for match in re.findall(
            r'<(?:a|button)\b[^>]*class=["\'][^"\']*common_btn[^"\']*["\'][^>]*>([\s\S]*?)</(?:a|button)>',
            button_box,
            flags=re.IGNORECASE,
        )
    ]
    action = next(
        (
            item
            for item in actions
            if item in {"예약하기", "예약마감", "접수종료", "예약 일시정지", "신청하기"}
        ),
        "",
    )

    return ServiceSnapshot(
        target_id=target.target_id,
        title=title or target.label or target.target_id,
        status=status,
        action=action,
        available=action == "예약하기",
        url=target.detail_url,
    )


def is_second_shift_barbecue(title: str) -> bool:
    compact = re.sub(r"\s+", "", title)
    return "바비큐존" in compact and "2차" in compact and re.search(r"17시~22시", compact) is not None


def parse_search_cards(page_html: str) -> list[SearchCard]:
    cards: list[SearchCard] = []
    card_pattern = re.compile(
        r"<li>[\s\S]*?fnDetailPage\('([^']+)'[\s\S]*?title=\"([^\"]+)\"[\s\S]*?</li>",
        flags=re.IGNORECASE,
    )
    for match in card_pattern.finditer(page_html):
        target_id = match.group(1)
        title = clean_text(match.group(2))
        card_html = match.group(0)
        if not is_second_shift_barbecue(title):
            continue
        status = first_text(card_html, r'<span\s+class=["\']bd_label\s+status\d+["\']>([\s\S]*?)</span>')
        cards.append(
            SearchCard(
                target_id=target_id,
                title=title,
                status=status,
                url=detail_url_for(target_id),
            )
        )
    return cards


def default_state() -> dict[str, Any]:
    return {"version": STATE_VERSION, "targets": {}}


def load_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(fallback)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json_if_changed(path: Path, data: dict[str, Any]) -> bool:
    encoded = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    if encoded == previous:
        return False
    path.write_text(encoded, encoding="utf-8")
    return True


def build_notifications(
    snapshots: list[ServiceSnapshot],
    previous_state: dict[str, Any],
    *,
    now: str,
    alert_on_first_available: bool,
) -> tuple[list[str], dict[str, Any]]:
    next_state = copy.deepcopy(previous_state) if previous_state else default_state()
    next_state["version"] = STATE_VERSION
    targets_state = next_state.setdefault("targets", {})
    notifications: list[str] = []

    for snapshot in snapshots:
        previous = targets_state.get(snapshot.target_id, {})
        had_previous = bool(previous)
        was_available = bool(previous.get("available"))
        already_notified = bool(previous.get("notified_available"))

        should_alert = snapshot.available and (
            (had_previous and not was_available)
            or (had_previous and not already_notified)
            or (not had_previous and alert_on_first_available)
        )

        if should_alert:
            notifications.append(format_notification(snapshot))

        if snapshot.available:
            notified_available = already_notified or should_alert or not alert_on_first_available
        else:
            notified_available = False

        changed = (
            previous.get("available") != snapshot.available
            or previous.get("action") != snapshot.action
            or previous.get("status") != snapshot.status
            or previous.get("title") != snapshot.title
        )
        notified_changed = previous.get("notified_available") != notified_available
        if had_previous and not changed and not notified_changed:
            continue

        targets_state[snapshot.target_id] = {
            "title": snapshot.title,
            "status": snapshot.status,
            "action": snapshot.action,
            "available": snapshot.available,
            "url": snapshot.url,
            "notified_available": notified_available,
            "last_changed_at": now if changed else previous.get("last_changed_at", now),
        }

    return notifications, next_state


def format_notification(snapshot: ServiceSnapshot) -> str:
    return "\n".join(
        [
            "서울 공공서비스예약 예약 가능",
            snapshot.title,
            f"상태: {snapshot.status or '-'}",
            f"버튼: {snapshot.action or '-'}",
            snapshot.url,
        ]
    )


def fetch_url(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(content_type, errors="replace")


def is_blocked_response(page_html: str) -> bool:
    return (
        "<!--dynapath:error-->" in page_html
        or bool(re.search(r"<h5[^>]*>\s*비정상 접근으로 인한 차단 알림\s*</h5>", page_html))
        or "정상 접근을 위해서는 인터넷 쿠키를 삭제" in page_html
    )


def load_config(path: Path) -> dict[str, Any]:
    return load_json(
        path,
        {
            "search": {"enabled": True, "query": "바비큐존", "max_pages": 2},
            "static_targets": [],
            "request_delay_seconds": 1.0,
            "request_timeout_seconds": 20.0,
            "alert_on_first_available": True,
        },
    )


def targets_from_config(config: dict[str, Any]) -> list[ServiceTarget]:
    targets = []
    for item in config.get("static_targets", []):
        targets.append(
            ServiceTarget(
                target_id=item["id"],
                label=item.get("label", ""),
                url=item.get("url", ""),
            )
        )
    return targets


def discover_targets(config: dict[str, Any]) -> list[ServiceTarget]:
    search = config.get("search", {})
    if not search.get("enabled", True):
        return []

    query = search.get("query", "바비큐존")
    max_pages = int(search.get("max_pages", 2))
    timeout = float(config.get("request_timeout_seconds", 20))
    delay = float(config.get("request_delay_seconds", 1))
    discovered: list[ServiceTarget] = []

    for page in range(1, max_pages + 1):
        params = urllib.parse.urlencode(
            {
                "code": "T500",
                "dCode": "T502",
                "sch_text": query,
                "currentPage": page,
            }
        )
        url = f"{BASE_URL}/web/search/selectPageListDetailSearchImg.do?{params}"
        try:
            page_html = fetch_url(url, timeout)
        except urllib.error.URLError as exc:
            print(f"warning: failed to fetch search page {page}: {exc}", file=sys.stderr)
            continue
        if is_blocked_response(page_html):
            print(f"warning: search page {page} was blocked by the reservation site", file=sys.stderr)
            continue
        discovered.extend(
            ServiceTarget(card.target_id, card.title, card.url)
            for card in parse_search_cards(page_html)
        )
        if page < max_pages:
            time.sleep(delay)
    return discovered


def merge_targets(*target_groups: list[ServiceTarget]) -> list[ServiceTarget]:
    merged: dict[str, ServiceTarget] = {}
    for group in target_groups:
        for target in group:
            merged[target.target_id] = target
    return list(merged.values())


def check_targets(targets: list[ServiceTarget], config: dict[str, Any]) -> list[ServiceSnapshot]:
    timeout = float(config.get("request_timeout_seconds", 20))
    delay = float(config.get("request_delay_seconds", 1))
    snapshots: list[ServiceSnapshot] = []
    for index, target in enumerate(targets):
        if index:
            time.sleep(delay)
        try:
            page_html = fetch_url(target.detail_url, timeout)
        except urllib.error.URLError as exc:
            print(f"warning: failed to fetch {target.target_id}: {exc}", file=sys.stderr)
            continue
        if is_blocked_response(page_html):
            print(f"warning: detail page for {target.target_id} was blocked", file=sys.stderr)
            continue
        snapshots.append(parse_detail_page(page_html, target))
    return snapshots


def send_telegram_message(text: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required when an alert is sent")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")
    request = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        if response.status >= 300:
            raise RuntimeError(f"Telegram API returned HTTP {response.status}: {body}")


def run_monitor(config_path: Path, state_path: Path, *, dry_run: bool = False) -> int:
    config = load_config(config_path)
    state = load_json(state_path, default_state())
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")

    discovered = discover_targets(config)
    configured = targets_from_config(config)
    targets = merge_targets(discovered, configured)

    if not targets:
        print("No targets found. Check monitor_config.json or site search results.")
        return 0

    snapshots = check_targets(targets, config)
    notifications, next_state = build_notifications(
        snapshots,
        state,
        now=now,
        alert_on_first_available=bool(config.get("alert_on_first_available", True)),
    )

    if notifications:
        for message in notifications:
            if dry_run:
                print("--- notification preview ---")
                print(message)
            else:
                send_telegram_message(message)

    changed = save_json_if_changed(state_path, next_state)
    print(f"Checked {len(snapshots)} targets; notifications={len(notifications)}; state_changed={changed}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor Seoul camping barbecue second-shift availability.")
    parser.add_argument("--config", default="monitor_config.json", help="Path to monitor config JSON.")
    parser.add_argument("--state", default="state.json", help="Path to persisted state JSON.")
    parser.add_argument("--dry-run", action="store_true", help="Print notifications instead of sending Telegram messages.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    return run_monitor(Path(args.config), Path(args.state), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
