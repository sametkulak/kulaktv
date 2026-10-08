#!/usr/bin/env python3
# Test script executed in GitHub Actions
"""Compare candidate Turkish IPTV sources using KulakTV's current health check.

This test never changes the production playlist. It compares candidate URLs against
the current main-branch channels.m3u and checks each genuinely new URL with the same
manifest + media-segment health test used by update_channels.py.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_channels import check_stream_url, parse_m3u  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "source-comparison.json"

CURRENT_PLAYLIST = "https://raw.githubusercontent.com/sametkulak/kulaktv/main/channels.m3u"
CANDIDATES = [
    ("iptv-turk-tr", "https://raw.githubusercontent.com/iptv-turk-tr/iptv/main/list.m3u", "m3u"),
    ("discevisita", "https://raw.githubusercontent.com/discevisita/iptv/main/tr.m3u", "m3u"),
    ("Free-TV/IPTV", "https://raw.githubusercontent.com/Free-TV/IPTV/master/lists/turkey.md", "free-tv-md"),
]


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "KulakTV-SourceComparison/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def parse_free_tv_turkey(text: str) -> list[dict[str, object]]:
    channels: list[dict[str, object]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|") or not "[>](" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name = re.sub(r"[ⓈⒼⓎ]$", "", cells[1]).strip()
        match = re.search(r"[>\]\((https?://[^)]+)\)", line)
        if not match:
            match = re.search(r"\[>\]\((https?://[^)]+)\)", line)
        if not match:
            continue
        url = match.group(1)
        channels.append({"name": name, "url": url, "alternatives": []})
    return channels


def urls_from_channels(channels: list[dict[str, object]]) -> set[str]:
    urls: set[str] = set()
    for channel in channels:
        url = str(channel.get("url") or "")
        if re.match(r"^https?://", url, re.I):
            urls.add(url)
        for alt in channel.get("alternatives", []) or []:
            alt_url = str(alt)
            if re.match(r"^https?://", alt_url, re.I):
                urls.add(alt_url)
    return urls


def main() -> int:
    started = datetime.now(timezone.utc).isoformat()

    current_text = fetch(CURRENT_PLAYLIST)
    current_channels = parse_m3u(current_text)
    current_urls = urls_from_channels(current_channels)

    source_data = []
    all_new_urls: set[str] = set()

    for name, url, parser_kind in CANDIDATES:
        text = fetch(url)
        channels = parse_free_tv_turkey(text) if parser_kind == "free-tv-md" else parse_m3u(text)
        urls = urls_from_channels(channels)
        new_urls = urls - current_urls
        all_new_urls.update(new_urls)
        source_data.append({
            "source": name,
            "url": url,
            "channels": len(channels),
            "candidateUrls": len(urls),
            "newUrls": sorted(new_urls),
            "newUrlCount": len(new_urls),
        })

    unique_new_urls = sorted(all_new_urls)
    print(f"Testing {len(unique_new_urls)} unique new URLs with current health check…")
    health: dict[str, dict[str, str]] = {}

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from update_channels import HEALTH_CHECK_WORKERS

    with ThreadPoolExecutor(max_workers=HEALTH_CHECK_WORKERS) as executor:
        futures = {executor.submit(check_stream_url, url): url for url in unique_new_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                status, detail = future.result()
            except Exception as exc:
                status, detail = "bad", str(exc)
            health[url] = {"status": status, "detail": detail}

    for item in source_data:
        new_urls = set(item["newUrls"])
        healthy = [url for url in new_urls if health.get(url, {}).get("status") == "ok"]
        failed = [url for url in new_urls if health.get(url, {}).get("status") == "bad"]
        item["newHealthyUrls"] = len(healthy)
        item["newFailedUrls"] = len(failed)
        item["newHealthyUrlList"] = sorted(healthy)
        item["newFailedUrlList"] = sorted(failed)

    all_healthy = sorted(url for url, result in health.items() if result.get("status") == "ok")

    payload = {
        "testedAt": started,
        "baseline": {
            "playlist": CURRENT_PLAYLIST,
            "channels": len(current_channels),
            "urls": len(current_urls),
        },
        "healthCheck": {
            "method": "M3U8 manifest + at least one media segment",
            "workers": HEALTH_CHECK_WORKERS,
            "uniqueNewUrlsTested": len(unique_new_urls),
            "healthy": len(all_healthy),
            "failed": len(unique_new_urls) - len(all_healthy),
        },
        "sources": source_data,
        "uniqueAcrossCandidates": {
            "newUrls": len(unique_new_urls),
            "newHealthyUrls": len(all_healthy),
            "newFailedUrls": len(unique_new_urls) - len(all_healthy),
        },
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    for item in source_data:
        print(
            f"{item['source']}: {item['candidateUrls']} URLs, "
            f"{item['newUrlCount']} new, {item['newHealthyUrls']} new healthy, "
            f"{item['newFailedUrls']} new failed"
        )
    print(
        f"UNIQUE across candidates: {len(unique_new_urls)} new URLs, "
        f"{len(all_healthy)} healthy, {len(unique_new_urls)-len(all_healthy)} failed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
