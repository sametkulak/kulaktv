#!/usr/bin/env python3
"""Refresh KulakTV's local M3U snapshot from the user-selected public source.

The browser loads ./channels.m3u from the same GitHub Pages origin. GitHub Actions
fetches the upstream playlist server-side, so the player does not need the upstream
provider to enable browser CORS. A failed fetch never replaces the last known-good
playlist.
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M3U_PATH = ROOT / "channels.m3u"
STATUS_PATH = ROOT / "update-status.json"
SOURCE_URL = "https://tinyurl.com/ByteFixRepairs2026"
USER_AGENT = "KulakTV-AutoUpdater/2.0"
MIN_CHANNELS = 10


def fetch_text(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=45) as response:
        final_url = response.geturl()
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace"), final_url


def parse_count(text: str) -> int:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    count = 0
    for i, line in enumerate(lines):
        if not line.strip().startswith("#EXTINF:"):
            continue
        for nxt in lines[i + 1:]:
            stripped = nxt.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                # Metadata between EXTINF and URL is allowed.
                continue
            if stripped.startswith(("http://", "https://")):
                count += 1
            break
    return count


def normalize_playlist(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[-1].strip():
        lines.pop()

    valid: list[str] = []
    for i, line in enumerate(lines):
        valid.append(line.rstrip())

    # Keep #EXTM3U as the first line because some players expect it there.
    header_line = next((x for x in valid if x.startswith("#EXTM3U")), "#EXTM3U")
    body = [x for x in valid if not x.startswith("#EXTM3U")]
    header = [
        header_line,
        "# KulakTV Auto-Updated Playlist",
        f"# Source: {SOURCE_URL}",
        f"# Last fetched: {datetime.now(timezone.utc).isoformat()}",
    ]
    content = "\n".join(body).strip()
    return "\n".join(header) + "\n" + (content + "\n" if content else "")


def write_status(payload: dict) -> None:
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    now = datetime.now(timezone.utc).astimezone()
    try:
        upstream_text, final_url = fetch_text(SOURCE_URL)
        count = parse_count(upstream_text)
        if count < MIN_CHANNELS:
            raise RuntimeError(
                f"Upstream playlist contains only {count} playable URL entries; refusing to replace the last good list."
            )

        new_text = normalize_playlist(upstream_text)
        old_text = M3U_PATH.read_text(encoding="utf-8") if M3U_PATH.exists() else ""
        changed = new_text != old_text
        if changed:
            M3U_PATH.write_text(new_text, encoding="utf-8")
            write_status(
                {
                    "status": "updated",
                    "updatedAt": now.isoformat(),
                    "source": SOURCE_URL,
                    "resolvedSource": final_url,
                    "channelCount": count,
                    "changed": True,
                }
            )
        print(
            f"KulakTV: source fetched successfully; {count} channels found; "
            f"playlist {'updated' if changed else 'already current'}."
        )
        return 0
    except Exception as exc:
        # Keep the last known-good channels.m3u and surface the problem in Actions.
        print(f"::warning::KulakTV source refresh failed: {exc}")
        print("Last known-good channels.m3u was kept; no repository file was changed.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
