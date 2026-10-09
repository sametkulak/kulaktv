#!/usr/bin/env python3
"""Discover public Turkish M3U sources on GitHub and maintain a small trial pool."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from update_channels import SOURCES, normalize_name, parse_m3u

ROOT = Path(__file__).resolve().parents[1]
PLAYLIST_PATH = ROOT / "channels.m3u"
STATE_PATH = ROOT / "discovered-sources.json"

SEARCH_QUERIES = [
    "extension:m3u turkey iptv",
    "extension:m3u turk iptv",
    "extension:m3u filename:tr.m3u",
    ""turk kanalları" m3u",
]
MAX_RESULTS_PER_QUERY = 30
MAX_CANDIDATES = 4
MIN_CHANNELS = 10
MIN_UNIQUE_URLS = 5
MIN_NEW_URL_RATIO = 0.15
MIN_AUTO_SCORE = 70
FETCH_TIMEOUT = 18
MAX_BODY = 3 * 1024 * 1024


def api_request(url: str) -> dict:
    headers = {
        "User-Agent": "KulakTV-Source-Discovery/1.0",
        "Accept": "application/vnd.github+json",
    }
    token = str(__import__("os").environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "KulakTV-Source-Discovery/1.0",
            "Accept": "application/vnd.apple.mpegurl,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        return response.read(MAX_BODY + 1)


def repo_meta(full_name: str) -> dict:
    return api_request(f"https://api.github.com/repos/{full_name}")


def freshness_score(pushed_at: str) -> float:
    if not pushed_at:
        return 25
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except Exception:
        return 25
    if days <= 7:
        return 100
    if days <= 30:
        return 90
    if days <= 90:
        return 75
    if days <= 180:
        return 55
    if days <= 365:
        return 35
    return 15


def static_score(channel_count: int, unique_urls: int, new_ratio: float, unique_hosts: int, pushed_at: str) -> int:
    channel_factor = min(1.0, channel_count / 80)
    diversity_factor = min(1.0, unique_hosts / max(unique_urls, 1) * 4)
    score = (
        40 * (new_ratio * 100)
        + 20 * (channel_factor * 100)
        + 20 * (diversity_factor * 100)
        + 20 * freshness_score(pushed_at)
    ) / 100
    return max(0, min(100, round(score)))


def load_previous() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "candidates": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 1, "candidates": []}
    except Exception:
        return {"version": 1, "candidates": []}


def main() -> int:
    current_urls = set()
    if PLAYLIST_PATH.exists():
        for line in PLAYLIST_PATH.read_text(encoding="utf-8").splitlines():
            if re.match(r"^https?://", line.strip(), re.I):
                current_urls.add(line.strip())

    known_urls = {url for _name, url in SOURCES}
    results_by_url: dict[str, dict[str, object]] = {}

    query_count = 0
    for query in SEARCH_QUERIES:
        params = urllib.parse.urlencode({"q": query, "per_page": MAX_RESULTS_PER_QUERY})
        try:
            data = api_request(f"https://api.github.com/search/code?{params}")
        except Exception as exc:
            print(f"::warning::GitHub kaynak araması başarısız ({query}): {exc}")
            continue
        query_count += 1

        for item in data.get("items", []):
            repo = item.get("repository") or {}
            full_name = str(repo.get("full_name") or "")
            path = str(item.get("path") or "")
            default_branch = str(repo.get("default_branch") or "main")
            if not full_name or not path:
                continue
            try:
                meta = repo_meta(full_name)
            except Exception:
                meta = repo
            if meta.get("fork") or meta.get("archived") or meta.get("disabled"):
                continue
            if not meta.get("default_branch"):
                meta["default_branch"] = default_branch
            raw_url = f"https://raw.githubusercontent.com/{full_name}/{quote(path)}?ref={quote(str(meta.get('default_branch') or default_branch))}"
            raw_url = raw_url.replace("?ref=", "/").replace("%2F", "/")
            if raw_url in known_urls or raw_url in results_by_url:
                continue
            try:
                payload = fetch_bytes(raw_url)
                if len(payload) > MAX_BODY:
                    continue
                text = payload.decode("utf-8-sig", errors="replace")
                channels = parse_m3u(text)
            except Exception:
                continue

            urls = []
            hosts = set()
            for channel in channels:
                primary = str(channel.get("url") or "")
                if re.match(r"^https?://", primary, re.I):
                    urls.append(primary)
                    try:
                        hosts.add(urllib.parse.urlsplit(primary).hostname or "")
                    except Exception:
                        pass
                for alt in channel.get("alternatives", []):
                    alt = str(alt)
                    if re.match(r"^https?://", alt, re.I):
                        urls.append(alt)
                        try:
                            hosts.add(urllib.parse.urlsplit(alt).hostname or "")
                        except Exception:
                            pass

            unique_urls = list(dict.fromkeys(urls))
            if len(channels) < MIN_CHANNELS or len(unique_urls) < MIN_UNIQUE_URLS:
                continue
            new_urls = [url for url in unique_urls if url not in current_urls]
            new_ratio = len(new_urls) / max(1, len(unique_urls))
            if new_ratio < MIN_NEW_URL_RATIO:
                continue

            pushed_at = str(meta.get("pushed_at") or repo.get("pushed_at") or "")
            score = static_score(len(channels), len(unique_urls), new_ratio, len(hosts), pushed_at)
            if score < 55:
                continue

            candidate = {
                "name": f"auto:{full_name}:{path}",
                "url": raw_url,
                "repo": full_name,
                "path": path,
                "channelCount": len(channels),
                "uniqueUrls": len(unique_urls),
                "uniqueHosts": len([host for host in hosts if host]),
                "newUrls": len(new_urls),
                "newUrlRatio": round(new_ratio, 3),
                "staticScore": score,
                "pushedAt": pushed_at,
                "status": "trial" if score >= MIN_AUTO_SCORE else "candidate",
                "urls": unique_urls[:160],
                "lastDiscoveredAt": datetime.now(timezone.utc).isoformat(),
            }
            results_by_url[raw_url] = candidate

    previous = load_previous()
    old = {
        str(item.get("url")): item
        for item in previous.get("candidates", [])
        if isinstance(item, dict) and item.get("url")
    }

    merged = []
    for url, candidate in results_by_url.items():
        previous_item = old.get(url, {})
        candidate["status"] = (
            "active"
            if previous_item.get("status") == "active"
            else "trial"
            if candidate["staticScore"] >= MIN_AUTO_SCORE
            else "candidate"
        )
        candidate["healthScore"] = previous_item.get("healthScore")
        candidate["lastHealthAt"] = previous_item.get("lastHealthAt")
        candidate["healthyUrls"] = previous_item.get("healthyUrls", 0)
        candidate["checkedUrls"] = previous_item.get("checkedUrls", 0)
        candidate["lastError"] = previous_item.get("lastError", "")
        merged.append(candidate)

    for url, previous_item in old.items():
        if url not in results_by_url:
            last_seen = str(previous_item.get("lastDiscoveredAt") or "")
            try:
                days = (datetime.now(timezone.utc) - datetime.fromisoformat(last_seen.replace("Z", "+00:00"))).total_seconds() / 86400
            except Exception:
                days = 999
            if previous_item.get("status") == "active" and days <= 7:
                merged.append(previous_item)

    merged.sort(key=lambda item: (item.get("status") not in {"active", "trial"}, -int(item.get("staticScore", 0))))
    active_count = sum(1 for item in merged if item.get("status") == "active")

    payload = {
        "version": 1,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "queryCount": query_count,
        "candidates": merged[:MAX_CANDIDATES],
        "activeAutoSources": active_count,
        "message": "Aday kaynaklar günlük GitHub taraması ve KulakTV sağlık kontrolüyle değerlendirilir.",
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Kaynak keşfi: {len(merged[:MAX_CANDIDATES])} aday, {active_count} aktif otomatik kaynak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
