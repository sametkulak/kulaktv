#!/usr/bin/env python3
"""Build KulakTV's playlist by merging several public M3U sources.

The browser always loads ./channels.m3u from the GitHub Pages origin. This script
runs server-side in GitHub Actions, so upstream playlist CORS policies do not
affect the list download.

Sources are merged by a normalized channel name. The first source has priority;
additional URLs for the same channel are written as Yedek1/Yedek2/... attributes
and can be tried by the web player in order.

A completely failed refresh never replaces the last known-good playlist.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M3U_PATH = ROOT / "channels.m3u"
STATUS_PATH = ROOT / "update-status.json"

SOURCES = [
    ("OnurEröz Türkiye", "https://onureroz.com/indirmeler/turk/index.m3u"),
    ("ByteFix Repairs", "https://tinyurl.com/ByteFixRepairs2026"),
    ("iptv-org Türkiye", "https://iptv-org.github.io/iptv/countries/tr.m3u"),
]

USER_AGENT = "KulakTV-AutoUpdater/3.0"
TIMEOUT = 45
MIN_CHANNELS = 10
MAX_ALTERNATIVES = 4


def fetch_text(url: str) -> tuple[str, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/x-mpegURL,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        final_url = response.geturl()
        raw = response.read()
    return raw.decode("utf-8-sig", errors="replace"), final_url


def parse_attrs(line: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r'([\w-]+)="([^"]*)"', line)
    }


def parse_m3u(text: str) -> list[dict[str, object]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    channels: list[dict[str, object]] = []
    pending: str | None = None
    current_meta: dict[str, str] = {}

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        upper = line.upper()
        if upper.startswith("#EXTINF:"):
            pending = line
            comma = line.find(",")
            meta = line[:comma] if comma >= 0 else line
            title = line[comma + 1 :].strip() if comma >= 0 else "İsimsiz Kanal"
            current_meta = parse_attrs(meta)

            # Some lists place attributes after the title portion as well.
            if title:
                match_name = re.search(r'^(.*?)(?:\s+)(?:tvg-name|group-title)=', title, re.I)
                if match_name:
                    title = match_name.group(1).strip()

            current_meta["_name"] = title
            continue

        if line.startswith("#"):
            continue

        if pending and re.match(r"^https?://", line, re.I):
            name = str(current_meta.get("_name") or "İsimsiz Kanal").strip()
            name = re.sub(
                r"\s*\[(?:Not 24/7|Geo-blocked)\]\s*$",
                "",
                name,
                flags=re.I,
            ).strip()

            alternatives: list[str] = []
            for key, value in current_meta.items():
                if key.lower().startswith(("yedek", "backup")) and re.match(
                    r"^https?://", value, re.I
                ):
                    if value != line and value not in alternatives:
                        alternatives.append(value)

            channels.append(
                {
                    "name": name,
                    "url": line,
                    "logo": current_meta.get("tvg-logo")
                    or current_meta.get("logo")
                    or "",
                    "group": current_meta.get("group-title")
                    or current_meta.get("group")
                    or "Diğer",
                    "tvg_id": current_meta.get("tvg-id") or "",
                    "alternatives": alternatives[:MAX_ALTERNATIVES],
                }
            )

            pending = None
            current_meta = {}

    return channels


def normalize_name(name: str) -> str:
    """Create a conservative key for matching variants such as TV 8 / TV8 HD."""
    value = unicodedata.normalize("NFKD", name)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.upper().replace("&", " AND ")
    value = re.sub(r"\b(FHD|HD|SD|LIVE|CANLI)\b", " ", value)
    value = re.sub(r"[^A-Z0-9]+", "", value)
    return value


def merge_channels(
    source_results: list[tuple[str, str, list[dict[str, object]]]]
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}

    for source_name, _source_url, channels in source_results:
        for channel in channels:
            name = str(channel["name"])
            key = normalize_name(name)
            if not key:
                key = name.strip().upper()

            urls = [str(channel["url"])]
            urls.extend(str(item) for item in channel.get("alternatives", []))
            urls = [item for item in urls if re.match(r"^https?://", item, re.I)]

            target = merged.get(key)
            if target is None:
                target = {
                    "name": name,
                    "url": urls[0],
                    "logo": str(channel.get("logo") or ""),
                    "group": str(channel.get("group") or "Diğer"),
                    "tvg_id": str(channel.get("tvg_id") or ""),
                    "alternatives": [],
                    "sources": [source_name],
                }
                merged[key] = target
            else:
                existing_sources = target.setdefault("sources", [])
                if source_name not in existing_sources:
                    existing_sources.append(source_name)

                if not target.get("logo") and channel.get("logo"):
                    target["logo"] = str(channel["logo"])

                current_group = str(target.get("group") or "Diğer")
                new_group = str(channel.get("group") or "Diğer")
                if current_group == "Diğer" and new_group != "Diğer":
                    target["group"] = new_group

            existing_urls = [str(target["url"])] + [
                str(item) for item in target["alternatives"]
            ]

            for url in urls:
                if url not in existing_urls and len(target["alternatives"]) < MAX_ALTERNATIVES:
                    target["alternatives"].append(url)
                    existing_urls.append(url)

    result = list(merged.values())
    for item in result:
        item.pop("sources", None)
    return result


def render_m3u(channels: list[dict[str, object]], fetched_at: str) -> str:
    lines = [
        "#EXTM3U",
        "# KulakTV multi-source playlist",
        "# Sources: OnurEröz Türkiye + ByteFix Repairs + iptv-org Türkiye",
        f"# Last merged: {fetched_at}",
    ]

    for channel in channels:
        name = str(channel["name"]).replace('"', "'")
        group = str(channel.get("group") or "Diğer").replace('"', "'")
        logo = str(channel.get("logo") or "").replace('"', "'")
        tvg_id = str(channel.get("tvg_id") or "").replace('"', "'")

        attrs = [f'tvg-id="{tvg_id}"', f'group-title="{group}"']
        if logo:
            attrs.insert(1, f'tvg-logo="{logo}"')

        alternatives = list(channel.get("alternatives") or [])
        for index, url in enumerate(alternatives, start=1):
            attrs.append(f'Yedek{index}="{str(url).replace(chr(34), chr(39))}"')

        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(str(channel["url"]))

    return "\n".join(lines) + "\n"


def write_status(payload: dict[str, object]) -> None:
    STATUS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    now = datetime.now(timezone.utc)
    fetched_at = now.isoformat()

    successful: list[tuple[str, str, list[dict[str, object]]]] = []
    failed: list[dict[str, str]] = []

    for source_name, source_url in SOURCES:
        try:
            text, final_url = fetch_text(source_url)
            channels = parse_m3u(text)
            if len(channels) < MIN_CHANNELS:
                raise RuntimeError(
                    f"only {len(channels)} valid M3U channels were found"
                )
            successful.append((source_name, final_url, channels))
            print(f"{source_name}: {len(channels)} channels")
        except Exception as exc:
            failed.append({"name": source_name, "url": source_url, "error": str(exc)})
            print(f"::warning::{source_name} failed: {exc}")

    if not successful:
        write_status(
            {
                "status": "fetch_failed",
                "updatedAt": fetched_at,
                "sourceCount": 0,
                "channelCount": 0,
                "sources": failed,
                "message": "No upstream source was available; last known-good playlist was kept.",
            }
        )
        print("No source succeeded. Keeping last known-good channels.m3u.")
        return 0

    merged = merge_channels(successful)
    if len(merged) < MIN_CHANNELS:
        raise RuntimeError(
            f"Merged playlist contains only {len(merged)} channels; refusing to replace the last good list."
        )

    new_text = render_m3u(merged, fetched_at)
    old_text = M3U_PATH.read_text(encoding="utf-8") if M3U_PATH.exists() else ""
    changed = new_text != old_text

    if changed:
        M3U_PATH.write_text(new_text, encoding="utf-8")

    write_status(
        {
            "status": "updated" if changed else "current",
            "updatedAt": fetched_at,
            "channelCount": len(merged),
            "sourceCount": len(successful),
            "changed": changed,
            "sources": [
                {
                    "name": name,
                    "url": configured_url,
                    "resolvedUrl": final_url,
                    "channelCount": len(channels),
                    "status": "ok",
                }
                for (name, final_url, channels), (_configured_name, configured_url) in zip(
                    successful, [item for item in SOURCES if any(item[0] == s[0] for s in successful)]
                )
            ]
            + failed,
            "message": (
                "Multi-source playlist merged successfully."
                if changed
                else "Merged playlist is already current."
            ),
        }
    )

    print(
        f"KulakTV: {len(merged)} unique channels merged from "
        f"{len(successful)}/{len(SOURCES)} sources; "
        f"playlist {'updated' if changed else 'already current'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
