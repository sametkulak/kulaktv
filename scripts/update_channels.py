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
HEALTH_STATE_PATH = ROOT / "health-state.json"

SOURCES = [
    ("OnurEröz Türkiye", "https://onureroz.com/indirmeler/turk/index.m3u"),
    ("ByteFix Repairs", "https://tinyurl.com/ByteFixRepairs2026"),
    ("iptv-org Türkiye", "https://iptv-org.github.io/iptv/countries/tr.m3u"),
]


# The workflow is intentionally limited to trusted public playlist sources above.
USER_AGENT = "KulakTV-AutoUpdater/3.1"
TIMEOUT = 45
MIN_CHANNELS = 10
MAX_ALTERNATIVES = 4

HEALTH_CHECK_ENABLED = True
HEALTH_CHECK_TIMEOUT = 8
HEALTH_CHECK_WORKERS = 12
HEALTH_MAX_URLS = 900
HEALTH_BODY_LIMIT = 128 * 1024

FAILED_STREAK_TO_REMOVE = 2
GLOBAL_HEALTH_MIN_RATIO = 0.20

LOGO_REPO_API = "https://api.github.com/repos/tv-logo/tv-logos/contents/countries/turkey"
LOGO_REPO_RAW = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/turkey"
LOGO_FETCH_TIMEOUT = 20

# Common M3U names that use a different filename in the logo repository.
LOGO_ALIASES = {
    "NR 1 TURK": "nr1-turk-hd-tr.png",
    "NR 1 TV": "nr1-tr.png",
    "POWER TURK": "powerturk-tr.png",
    "POWER TV AKUSTIK": "power-tv-hd-tr.png",
    "TH TURK HABER TV": "turk-haber-tr.png",
    "KANAL ON 4 TV": "on4-tv-tr.png",
    "BURSA LINE TV": "line-tv-tr.png",
    "MAVI KARADENIZ TV": "mavi-karadeniz-tr.png",
    "EURO D HD SS": "euro-d-tr.png",
}

# Preferred display order for major Turkish channels. Only channels that
# actually exist in the merged playlist are included. The order is applied
# inside each health tier, so healthy channels still stay above failed ones.
PRIORITY_CHANNELS = [
    "ATV",
    "KANAL D",
    "STAR TV",
    "TRT 1",
    "SHOW TV",
    "NOW",
    "TV8",
    "BEYAZ TV",
    "CNN TÜRK",
    "A HABER",
    "TRT HABER",
    "SÖZCÜ TV",
    "HALK TV",
    "A SPOR",
    "TRT SPOR",
    "KANAL 7",
    "NTV",
    "TV100",
    "HABERTÜRK",
    "HABER GLOBAL",
    "TGRT HABER",
    "24 TV",
    "TV8,5",
    "TRT SPOR YILDIZ",
    "TRT BELGESEL",
    "TRT 2",
    "TRT MÜZİK",
    "TRT ÇOCUK",
    "TRT TÜRK",
    "TRT AVAZ",
    "360 TV",
    "FLASH HABER",
    "TELE1",
    "KRT TV",
    "TV5",
    "ÜLKE TV",
    "KANAL 24",
    "BLOOMBERG HT",
    "A PARA",
    "EKOTÜRK",
    "SPORTS TV",
    "TİVİBU SPOR",
    "FB TV",
    "GS TV",
    "HT SPOR",
    "KRAL POP TV",
    "DREAM TÜRK",
    "POWERTÜRK TV",
    "NUMBER1 TV",
    "NR1 TÜRK",
]

# Small name aliases for common variants found in M3U sources.
PRIORITY_ALIASES = {
    "NOW TV": "NOW",
    "KANAL24": "KANAL 24",
}


def load_health_state() -> dict[str, dict[str, object]]:
    if not HEALTH_STATE_PATH.exists():
        return {}
    try:
        data = json.loads(HEALTH_STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_health_state(state: dict[str, dict[str, object]]) -> None:
    HEALTH_STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def check_stream_url(url: str) -> tuple[str, str]:
    """Check that a public HLS/M3U8 manifest is reachable and looks like HLS."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(HEALTH_BODY_LIMIT).decode(
                "utf-8-sig", errors="replace"
            )

        if not (200 <= status < 300):
            return "bad", f"HTTP {status}"
        if "#EXTM3U" not in body.upper():
            return "bad", "response is not a valid M3U8 manifest"
        return "ok", f"HTTP {status}" + (f" • {content_type}" if content_type else "")
    except Exception as exc:
        return "bad", str(exc)


def health_check_urls(urls: list[str]) -> dict[str, dict[str, str]]:
    """Check unique stream URLs with modest concurrency and no retry storm."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    unique = list(dict.fromkeys(urls))[:HEALTH_MAX_URLS]
    if not HEALTH_CHECK_ENABLED or not unique:
        return {
            url: {"status": "unknown", "detail": "health check disabled"}
            for url in unique
        }

    results: dict[str, dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=HEALTH_CHECK_WORKERS) as executor:
        futures = {executor.submit(check_stream_url, url): url for url in unique}
        for future in as_completed(futures):
            url = futures[future]
            try:
                status, detail = future.result()
            except Exception as exc:
                status, detail = "bad", str(exc)
            results[url] = {"status": status, "detail": detail}
    return results


def order_urls(urls: list[str], health: dict[str, dict[str, str]]) -> list[str]:
    """Healthy first, untested next, failed last while preserving original order."""
    tiers = {"ok": 0, "unknown": 1, "bad": 2}
    return sorted(
        list(dict.fromkeys(urls)),
        key=lambda url: tiers.get(health.get(url, {}).get("status", "unknown"), 1),
    )


def channel_health(channel: dict[str, object]) -> tuple[bool, bool]:
    """Return (has_healthy_url, has_any_checked_url)."""
    checked = channel.get("health") or {}
    if not checked:
        return False, False
    return any(item.get("status") == "ok" for item in checked.values()), True


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

    source_order = 0

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
                    "_sourceOrder": source_order,
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

            source_order += 1

            existing_urls = [str(target["url"])] + [
                str(item) for item in target["alternatives"]
            ]

            for url in urls:
                if url not in existing_urls and len(target["alternatives"]) < MAX_ALTERNATIVES:
                    target["alternatives"].append(url)
                    existing_urls.append(url)

    result = list(merged.values())

    all_urls: list[str] = []
    for item in result:
        all_urls.append(str(item["url"]))
        all_urls.extend(str(value) for value in item["alternatives"])

    health = health_check_urls(all_urls)

    for item in result:
        urls = [str(item["url"])] + [str(value) for value in item["alternatives"]]
        ordered = order_urls(urls, health)
        item["url"] = ordered[0]
        item["alternatives"] = ordered[1:1 + MAX_ALTERNATIVES]
        item["health"] = {
            url: health.get(url, {"status": "unknown", "detail": "not checked"})
            for url in ordered
        }
        item.pop("sources", None)

    return result



def fetch_turkey_logo_index() -> dict[str, str]:
    """Return exact filename matches from the public Turkey logo directory."""
    from urllib.parse import urlencode

    index: dict[str, str] = {}
    try:
        for page in range(1, 8):
            query = urlencode({"ref": "main", "per_page": 100, "page": page})
            req = urllib.request.Request(
                f"{LOGO_REPO_API}?{query}",
                headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=LOGO_FETCH_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
            if not isinstance(payload, list) or not payload:
                break
            for item in payload:
                if item.get("type") == "file" and str(item.get("name", "")).lower().endswith(".png"):
                    filename = str(item["name"])
                    key = normalize_name(filename.rsplit(".png", 1)[0].rsplit("-tr", 1)[0])
                    if key:
                        index.setdefault(key, filename)
            if len(payload) < 100:
                break
    except Exception as exc:
        print(f"::warning::Logo index could not be loaded: {exc}")
    return index


def enrich_missing_logos(channels: list[dict[str, object]]) -> int:
    """Fill missing logo URLs with exact matches from tv-logo/tv-logos."""
    logo_index = fetch_turkey_logo_index()
    if not logo_index:
        return 0

    filled = 0
    for channel in channels:
        if str(channel.get("logo") or "").strip():
            continue

        name = str(channel.get("name") or "").strip()
        alias_filename = LOGO_ALIASES.get(normalize_name(name))
        filename = alias_filename

        if not filename:
            filename = logo_index.get(normalize_name(name))

        if not filename:
            # Try the common filename pattern only when that exact file exists.
            slug_key = normalize_name(name)
            filename = logo_index.get(slug_key)

        if filename:
            channel["logo"] = f"{LOGO_REPO_RAW}/{filename}"
            filled += 1

    return filled


def apply_health_policy(
    channels: list[dict[str, object]],
    previous_state: dict[str, dict[str, object]],
    checked_at: str,
    global_health_ratio: float,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]], dict[str, int]]:
    """Keep one-day failures, remove after two consecutive failed runs, and sort healthy first."""
    degraded = global_health_ratio < GLOBAL_HEALTH_MIN_RATIO
    next_state: dict[str, dict[str, object]] = {}
    kept: list[dict[str, object]] = []
    removed = 0
    pending = 0

    for channel in channels:
        key = normalize_name(str(channel["name"])) or str(channel["name"]).strip().upper()
        has_healthy, has_checked = channel_health(channel)
        old = previous_state.get(key, {})
        streak = int(old.get("failedStreak", 0) or 0)

        if has_healthy:
            streak = 0
        elif has_checked and not degraded:
            streak += 1
        else:
            # A globally degraded health-check run should not age channels toward deletion.
            streak = streak

        next_state[key] = {
            "name": str(channel["name"]),
            "failedStreak": streak,
            "lastCheckedAt": checked_at,
            "lastHealthyAt": checked_at if has_healthy else old.get("lastHealthyAt"),
            "hasHealthyUrl": has_healthy,
        }

        if streak >= FAILED_STREAK_TO_REMOVE and has_checked and not has_healthy and not degraded:
            removed += 1
            continue

        if streak == 1 and has_checked and not has_healthy:
            pending += 1

        # Healthy channels first; one-day failures follow; unknowns stay after those.
        channel["_healthTier"] = 0 if has_healthy else (2 if has_checked else 1)
        kept.append(channel)

    # Preserve the health policy first: healthy channels stay above
    # one-day failures. Inside each tier, preferred channels use the
    # explicit display order above; everything else keeps source order.
    priority_map = {
        normalize_name(name): index
        for index, name in enumerate(PRIORITY_CHANNELS, start=1)
    }
    alias_map = {
        normalize_name(source): normalize_name(target)
        for source, target in PRIORITY_ALIASES.items()
    }

    def priority_key(item: dict[str, object]) -> tuple[int, int, int]:
        name_key = normalize_name(str(item["name"]))
        priority = priority_map.get(name_key)
        if priority is None:
            priority = priority_map.get(alias_map.get(name_key, ""), len(PRIORITY_CHANNELS) + 1)
        return (
            int(item.pop("_healthTier", 1)),
            priority,
            int(item.pop("_sourceOrder", 10**9)),
        )

    kept.sort(key=priority_key)
    return kept, next_state, {
        "degraded": int(degraded),
        "pendingRemoval": pending,
        "removed": removed,
    }


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
    logos_filled = enrich_missing_logos(merged)
    print(f"Logo enrichment: {logos_filled} missing channel logos filled.")

    health_summary = {"checked": 0, "healthy": 0, "failed": 0}
    health_failures: list[dict[str, str]] = []
    for channel in merged:
        for url, result in (channel.get("health") or {}).items():
            health_summary["checked"] += 1
            if result.get("status") == "ok":
                health_summary["healthy"] += 1
            elif result.get("status") == "bad":
                health_summary["failed"] += 1
                if len(health_failures) < 30:
                    health_failures.append({
                        "channel": str(channel["name"]),
                        "url": url,
                        "detail": str(result.get("detail") or "unknown"),
                    })
        channel.pop("health", None)

    previous_health_state = load_health_state()
    ratio = (
        health_summary["healthy"] / health_summary["checked"]
        if health_summary["checked"]
        else 0.0
    )
    merged, next_health_state, removal_summary = apply_health_policy(
        merged,
        previous_health_state,
        fetched_at,
        ratio,
    )

    if len(merged) < MIN_CHANNELS:
        raise RuntimeError(
            f"Merged playlist contains only {len(merged)} channels after health filtering; refusing to replace the last good list."
        )

    save_health_state(next_health_state)

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
            "logosFilled": logos_filled,
            "healthCheck": {
                "enabled": HEALTH_CHECK_ENABLED,
                "checkedUrls": health_summary["checked"],
                "healthyUrls": health_summary["healthy"],
                "failedUrls": health_summary["failed"],
                "failures": health_failures,
                "ordering": "healthy-first, failed-last",
                "globalHealthDegraded": bool(removal_summary["degraded"]),
                "pendingRemoval": removal_summary["pendingRemoval"],
                "removedAfterTwoFailures": removal_summary["removed"],
            },
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
