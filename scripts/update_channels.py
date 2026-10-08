#!/usr/bin/env python3
"""Conservatively refresh KulakTV's built-in M3U URLs from iptv-org.

Only existing KulakTV channels are considered. A URL is replaced only when the
upstream playlist offers the same channel with a host in the allowlist below,
or with exactly the same hostname as the current KulakTV URL.

This avoids importing arbitrary third-party streams from a large community
playlist while still letting changed paths/URLs propagate automatically.
"""
from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
M3U_PATH = ROOT / "channels.m3u"
STATUS_PATH = ROOT / "update-status.json"
SOURCE_URL = "https://iptv-org.github.io/iptv/countries/tr.m3u"

# Domains we are comfortable using for the channels already carried by KulakTV.
# Exact-host matching is also allowed, so an already-known host can keep updating
# its path even if it is not listed here.
SAFE_HOST_SUFFIXES = (
    ".trt.com.tr",
    ".daioncdn.net",
    ".ercdn.net",
    ".tgrthaber.com",
    ".tjk.org",
    ".ensonhaber.com",
    "tele1-live.ercdn.net",
)


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "KulakTV-AutoUpdater/1.0 (+https://github.com/)"
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_m3u(text: str) -> list[tuple[str, str, str, str]]:
    """Return tuples of (extinf_line, channel_name, tvg_id, url)."""
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[tuple[str, str, str, str]] = []
    for i, line in enumerate(lines):
        if not line.startswith("#EXTINF:"):
            continue
        comma = line.find(",")
        name = line[comma + 1 :].strip() if comma >= 0 else ""
        tvg = re.search(r'tvg-id="([^"]*)"', line)
        tvg_id = tvg.group(1).strip() if tvg else ""
        url = ""
        for j in range(i + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt or nxt.startswith("#"):
                continue
            url = nxt
            break
        if url.startswith(("http://", "https://")):
            out.append((line, name, tvg_id, url))
    return out


def normalize_name(name: str) -> str:
    name = re.sub(r"\s*\([^)]*\)", "", name)
    name = re.sub(r"\s*\[(?:Not 24/7|Geo-blocked)\]\s*$", "", name, flags=re.I)
    name = re.sub(r"[^\w\u00c0-\u024f\u1e00-\u1eff ]+", " ", name, flags=re.UNICODE)
    return " ".join(name.casefold().split())


def allowed_upstream(url: str, current_url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    current_host = (urlparse(current_url).hostname or "").lower()
    if not host:
        return False
    if host == current_host:
        return True
    return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in SAFE_HOST_SUFFIXES)


def main() -> None:
    local_text = M3U_PATH.read_text(encoding="utf-8")
    upstream_text = fetch_text(SOURCE_URL)
    local = parse_m3u(local_text)
    upstream = parse_m3u(upstream_text)

    by_tvg: dict[str, list[tuple[str, str, str, str]]] = {}
    by_name: dict[str, list[tuple[str, str, str, str]]] = {}
    for item in upstream:
        _, name, tvg, url = item
        if tvg:
            by_tvg.setdefault(tvg.casefold(), []).append(item)
        by_name.setdefault(normalize_name(name), []).append(item)

    lines = local_text.replace("\r\n", "\n").split("\n")
    updates = 0
    retained = 0

    # Replace only URL lines that belong to a local #EXTINF record.
    for idx, line in enumerate(lines):
        if not line.startswith("#EXTINF:"):
            continue
        comma = line.find(",")
        name = line[comma + 1 :].strip() if comma >= 0 else ""
        tvg = re.search(r'tvg-id="([^"]*)"', line)
        tvg_id = tvg.group(1).strip() if tvg else ""

        url_idx = None
        current_url = None
        for j in range(idx + 1, len(lines)):
            nxt = lines[j].strip()
            if not nxt or nxt.startswith("#"):
                continue
            if nxt.startswith(("http://", "https://")):
                url_idx = j
                current_url = nxt
            break
        if url_idx is None or current_url is None:
            continue

        candidates = []
        if tvg_id:
            candidates.extend(by_tvg.get(tvg_id.casefold(), []))
        if not candidates:
            candidates.extend(by_name.get(normalize_name(name), []))

        # Prefer the first safe candidate that is not an obviously non-24/7/geo-blocked duplicate.
        selected = None
        for item in candidates:
            extinf, up_name, up_tvg, up_url = item
            if "[Not 24/7]" in extinf or "[Geo-blocked]" in extinf:
                continue
            if allowed_upstream(up_url, current_url):
                selected = up_url
                break
        if selected:
            if selected != current_url:
                lines[url_idx] = selected
                updates += 1
            else:
                retained += 1

    # Keep all local comments/metadata intact.
    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    M3U_PATH.write_text(new_text, encoding="utf-8")

    now = datetime.now(timezone.utc).astimezone()
    STATUS_PATH.write_text(
        __import__("json").dumps(
            {
                "updatedAt": now.isoformat(),
                "source": SOURCE_URL,
                "localChannels": len(local),
                "upstreamChannels": len(upstream),
                "urlsChanged": updates,
                "channelsWithSafeMatch": retained + updates,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"KulakTV: {updates} URL updated, {retained} kept, {len(local)} local channels checked.")


if __name__ == "__main__":
    main()
