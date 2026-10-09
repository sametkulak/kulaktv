# MANUAL-HEALTH-SCAN-2026-10-09
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
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
M3U_PATH = ROOT / "channels.m3u"
STATUS_PATH = ROOT / "update-status.json"
HEALTH_STATE_PATH = ROOT / "health-state.json"
SOURCE_QUALITY_PATH = ROOT / "source-quality.json"
PLAYER_TELEMETRY_PATH = ROOT / "player-telemetry.json"
EPG_STATUS_PATH = ROOT / "epg-status.json"
DISCOVERY_PATH = ROOT / "discovered-sources.json"
HISTORY_PATH = ROOT / "update-history.json"

SOURCES = [
    ("OnurEröz Türkiye", "https://onureroz.com/indirmeler/turk/index.m3u"),
    ("ByteFix Repairs", "https://tinyurl.com/ByteFixRepairs2026"),
    ("iptv-org Türkiye", "https://iptv-org.github.io/iptv/countries/tr.m3u"),
    ("discevisita", "https://raw.githubusercontent.com/discevisita/iptv/main/tr.m3u"),
    ("iptv-turk-tr", "https://raw.githubusercontent.com/iptv-turk-tr/iptv/main/list.m3u"),
    ("rideordie16/tv", "https://raw.githubusercontent.com/rideordie16/tv/main/tv2.m3u"),
    ("qazim/IPTV", "https://raw.githubusercontent.com/qazim/IPTV/main/TurkAzeri.m3u"),
    ("ilyswch/IPTV-TR", "https://raw.githubusercontent.com/ilyswch/IPTV-TR/main/box.m3u"),
]


# The workflow starts with the fixed trusted sources above and may add a very small
# trial pool discovered by the separate GitHub source-discovery job.
USER_AGENT = "KulakTV-AutoUpdater/3.1"


def load_json_object(path: Path, default: dict[str, object] | None = None) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else (default or {})
    except Exception:
        return default or {}


def get_configured_sources() -> list[tuple[str, str]]:
    """Return the fixed sources plus a tiny automatically discovered trial/active pool."""
    configured = list(SOURCES)
    document = load_json_object(DISCOVERY_PATH, {})
    existing = {url for _name, url in configured}
    candidates = document.get("candidates", [])
    if not isinstance(candidates, list):
        return configured

    eligible = [
        item for item in candidates
        if isinstance(item, dict)
        and item.get("status") in {"active", "trial"}
        and str(item.get("url") or "").startswith(("http://", "https://"))
        and str(item.get("url")) not in existing
    ]
    eligible.sort(
        key=lambda item: (
            item.get("status") != "active",
            -int(item.get("healthScore") or 0),
            -int(item.get("staticScore") or 0),
        )
    )
    for item in eligible[:AUTO_SOURCE_MAX]:
        configured.append((str(item.get("name")), str(item.get("url"))))
    return configured
TIMEOUT = 45
MIN_CHANNELS = 10
MAX_ALTERNATIVES = 9
# Kalite algoritması kanal başına en fazla 12 adayı test eder; oynatıcıya en iyi 10 (ana + 9 yedek) yazılır.
MAX_QUALITY_CANDIDATES = 12
AUTO_SOURCE_MAX = 4
# Güvenilmez yayın sunucuları
BLOCKED_STREAM_HOSTS = {
    "helga.iptv2022.com",
}

def is_blocked_stream_url(url: str) -> bool:
    try:
        return (urlsplit(url).hostname or "").lower() in BLOCKED_STREAM_HOSTS
    except Exception:
        return False

HEALTH_CHECK_ENABLED = True
HEALTH_CHECK_TIMEOUT = 12
HEALTH_CHECK_WORKERS = 12
HEALTH_MAX_URLS = 900
HEALTH_BODY_LIMIT = 128 * 1024
HEALTH_SEGMENT_READ_LIMIT = 4096
HEALTH_MANIFEST_DEPTH = 2

FAILED_STREAK_TO_REMOVE = 2
GLOBAL_HEALTH_MIN_RATIO = 0.20

LOGO_REPO_API = "https://api.github.com/repos/tv-logo/tv-logos/contents/countries/turkey"
LOGO_REPO_RAW = "https://raw.githubusercontent.com/tv-logo/tv-logos/main/countries/turkey"
LOGO_FETCH_TIMEOUT = 20

# Common M3U names that use a different filename in the logo repository.
# Explicit logos for channels where a public M3U source has a reliable
# branded image that should win over placeholder/initial logos.
PREFERRED_CHANNEL_LOGOS = {
    "NOW": "https://i.imgur.com/5EYjWK7.png",
}

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
    "NOWTV": "NOW",
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


def load_source_quality() -> dict[str, object]:
    if not SOURCE_QUALITY_PATH.exists():
        return {}
    try:
        data = json.loads(SOURCE_QUALITY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def load_player_telemetry() -> dict[str, object]:
    if not PLAYER_TELEMETRY_PATH.exists():
        return {}
    try:
        data = json.loads(PLAYER_TELEMETRY_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def player_quality_score(record: dict[str, object]) -> int:
    successes = int(record.get("successes", 0) or 0)
    failures = int(record.get("failures", 0) or 0)
    stalls = int(record.get("stalls", 0) or 0)
    bad = failures + stalls * 0.75
    total = successes + bad
    if total <= 0:
        return 50

    score = ((successes + 3) / (total + 6)) * 100
    latency_count = int(record.get("latencyCount", 0) or 0)
    if latency_count:
        average = float(record.get("latencySumMs", 0) or 0) / latency_count
        if average < 3000:
            score += 5
        elif average > 10000:
            score -= 10

    return max(0, min(100, round(score)))


def apply_player_quality(
    quality: dict[str, dict[str, object]],
    telemetry: dict[str, object],
    checked_at: str | None = None,
) -> dict[str, dict[str, object]]:
    player_sources = telemetry.get("sources", {}) if isinstance(telemetry, dict) else {}
    if not isinstance(player_sources, dict):
        player_sources = {}

    for url, record in quality.items():
        player = player_sources.get(url)
        if not isinstance(player, dict):
            continue

        player_events = int(player.get("events", 0) or 0)
        if player_events <= 0:
            continue

        # Always recompute the pure server-health score from its raw
        # history. Do not feed a previously blended score back into the
        # weighting step, otherwise the client signal compounds every run.
        health_score = source_quality_score(record)
        player_score = player_quality_score(player)

        # Client data becomes influential gradually so a handful of browsers
        # cannot immediately overturn the server-side health history.
        weight = min(0.35, 0.10 + (min(player_events, 500) / 500) * 0.25)
        combined = round(health_score * (1 - weight) + player_score * weight)

        record["healthScore"] = health_score
        record["playerScore"] = player_score
        record["playerEvents"] = player_events
        record["playerSuccesses"] = int(player.get("successes", 0) or 0)
        record["playerFailures"] = int(player.get("failures", 0) or 0)
        record["playerStalls"] = int(player.get("stalls", 0) or 0)
        record["playerWeight"] = round(weight, 3)
        record["score"] = max(0, min(100, combined))
        record["label"] = (
            "Çok iyi" if record["score"] >= 85 else
            "İyi" if record["score"] >= 70 else
            "Orta" if record["score"] >= 50 else
            "Zayıf"
        )
        if player.get("lastEventAt"):
            record["lastPlayerEventAt"] = player["lastEventAt"]

    return quality


def source_quality_score(record: dict[str, object]) -> int:
    successes = int(record.get("successes", 0) or 0)
    failures = int(record.get("failures", 0) or 0)
    recovered = int(record.get("retryRecovered", 0) or 0)
    total = successes + failures
    if total <= 0:
        return 50

    score = ((successes + 4) / (total + 8)) * 100
    score -= min(12, recovered * 0.6)

    if record.get("lastStatus") == "ok":
        score += 2
    elif record.get("lastStatus") == "bad":
        score -= 7

    return max(0, min(100, round(score)))


def update_source_quality(
    previous: dict[str, object],
    snapshot: list[tuple[str, str, dict[str, str]]],
    checked_at: str,
    provider_map: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, object]]:
    next_quality: dict[str, dict[str, object]] = {}

    for channel_name, url, result in snapshot:
        status = str(result.get("status") or "unknown")
        detail = str(result.get("detail") or "")
        old = previous.get(url, {}) if isinstance(previous, dict) else {}

        record = {
            "url": url,
            "channel": channel_name,
            "host": urlsplit(url).hostname or "",
            "checks": int(old.get("checks", 0) or 0) + 1,
            "successes": int(old.get("successes", 0) or 0),
            "failures": int(old.get("failures", 0) or 0),
            "retryRecovered": int(old.get("retryRecovered", 0) or 0),
            "lastStatus": status,
            "lastCheckedAt": checked_at,
            "lastSuccessAt": old.get("lastSuccessAt"),
            "lastFailureAt": old.get("lastFailureAt"),
            "providers": list(provider_map.get(url, old.get("providers", []))) if provider_map else list(old.get("providers", [])),
        }

        if status == "ok":
            record["successes"] += 1
            record["lastSuccessAt"] = checked_at
            if "ikinci test başarılı" in detail.lower():
                record["retryRecovered"] += 1
        elif status == "bad":
            record["failures"] += 1
            record["lastFailureAt"] = checked_at

        record["score"] = source_quality_score(record)
        record["label"] = (
            "Çok iyi" if record["score"] >= 85 else
            "İyi" if record["score"] >= 70 else
            "Orta" if record["score"] >= 50 else
            "Zayıf"
        )
        next_quality[url] = record

    # Shared client playback telemetry is blended into the same score that
    # every player downloads from GitHub Pages.
    next_quality = apply_player_quality(
        next_quality,
        load_player_telemetry(),
        checked_at,
    )
    return next_quality


def save_source_quality(
    quality: dict[str, dict[str, object]],
    checked_at: str,
    providers: dict[str, dict[str, object]] | None = None,
) -> None:
    previous = load_source_quality()
    payload = {
        "version": 2,
        "updatedAt": checked_at,
        "algorithm": "server-health-plus-player-v2",
        "sourceCount": len(quality),
        "providers": providers if providers is not None else previous.get("providers", {}),
        "sources": quality,
    }
    SOURCE_QUALITY_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fetch_health_text(url: str, accept: str, read_limit: int) -> tuple[str, str, str]:
    """Fetch a small amount of text and return body, final URL, and content type."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
        },
    )
    with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as response:
        status = getattr(response, "status", 200)
        if not (200 <= status < 300):
            raise RuntimeError(f"HTTP {status}")
        final_url = response.geturl()
        content_type = str(response.headers.get("Content-Type") or "")
        body = response.read(read_limit).decode("utf-8-sig", errors="replace")
    return body, final_url, content_type


def find_hls_reference(manifest: str, base_url: str) -> tuple[str | None, str | None]:
    """Find a child playlist or media segment referenced by an HLS manifest."""
    lines = [line.strip() for line in manifest.replace("\r", "\n").split("\n")]
    for index, line in enumerate(lines):
        if not line or line.startswith("#"):
            continue
        if re.match(r"^https?://", line, re.I):
            return line, "reference"
        if index > 0 and lines[index - 1].startswith("#EXT-X-STREAM-INF"):
            return urljoin(base_url, line), "playlist"
        if index > 0 and lines[index - 1].startswith("#EXTINF:"):
            return urljoin(base_url, line), "segment"

    # Some manifests can contain absolute/relative media references without a
    # directly adjacent EXTINF marker. Return the first safe URI-like line.
    for line in lines:
        if line and not line.startswith("#"):
            candidate = line if re.match(r"^https?://", line, re.I) else urljoin(base_url, line)
            if re.match(r"^https?://", candidate, re.I):
                return candidate, "reference"
    return None, None


def verify_media_segment(segment_url: str) -> tuple[bool, str]:
    """Verify that one referenced media segment can actually be fetched."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Range": f"bytes=0-{HEALTH_SEGMENT_READ_LIMIT - 1}",
    }

    try:
        req = urllib.request.Request(segment_url, headers=headers)
        with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as response:
            status = getattr(response, "status", 200)
            if not (200 <= status < 300):
                return False, f"segment HTTP {status}"
            response.read(HEALTH_SEGMENT_READ_LIMIT)
        return True, f"segment HTTP {status}"
    except Exception as first_error:
        # Some HLS/CDN endpoints reject Range requests even though a normal
        # GET works. Retry once without Range, still reading only a small prefix.
        try:
            req = urllib.request.Request(
                segment_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=HEALTH_CHECK_TIMEOUT) as response:
                status = getattr(response, "status", 200)
                if not (200 <= status < 300):
                    return False, f"segment HTTP {status}"
                response.read(HEALTH_SEGMENT_READ_LIMIT)
            return True, f"segment HTTP {status} (normal GET)"
        except Exception:
            return False, f"segment unavailable: {first_error}"


def check_stream_url(url: str) -> tuple[str, str]:
    """Require a valid manifest and at least one reachable media segment."""
    try:
        manifest, final_url, content_type = fetch_health_text(
            url,
            "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*",
            HEALTH_BODY_LIMIT,
        )
        if "#EXTM3U" not in manifest.upper():
            return "bad", "response is not a valid M3U8 manifest"

        current_manifest = manifest
        current_url = final_url
        segment_url = None
        visited = {current_url}

        # Direct media playlist: grab a segment. Master playlist: follow up to
        # HEALTH_MANIFEST_DEPTH child playlists first, then verify one segment.
        for depth in range(HEALTH_MANIFEST_DEPTH + 1):
            reference, kind = find_hls_reference(current_manifest, current_url)
            if not reference:
                break

            if kind == "segment":
                segment_url = reference
                break

            if not re.match(r"^https?://", reference, re.I) or reference in visited:
                break
            visited.add(reference)

            child, child_final_url, child_content_type = fetch_health_text(
                reference,
                "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*",
                HEALTH_BODY_LIMIT,
            )
            if "#EXTM3U" not in child.upper():
                segment_url = reference
                break
            current_manifest = child
            current_url = child_final_url

        if not segment_url:
            return "bad", "manifest reachable but no media segment reference was found"

        segment_ok, segment_detail = verify_media_segment(segment_url)
        if not segment_ok:
            return "bad", segment_detail

        manifest_detail = f"manifest HTTP 2xx" + (f" • {content_type}" if content_type else "")
        return "ok", f"{manifest_detail} • {segment_detail}"
    except Exception as exc:
        return "bad", str(exc)


def health_check_urls(urls: list[str]) -> dict[str, dict[str, str]]:
    """Check unique stream URLs, then retry failed URLs once."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    unique = list(dict.fromkeys(urls))[:HEALTH_MAX_URLS]

    if not HEALTH_CHECK_ENABLED or not unique:
        return {
            url: {"status": "unknown", "detail": "health check disabled"}
            for url in unique
        }

    def run_check_pass(check_urls: list[str]) -> dict[str, dict[str, str]]:
        results: dict[str, dict[str, str]] = {}

        with ThreadPoolExecutor(max_workers=HEALTH_CHECK_WORKERS) as executor:
            futures = {
                executor.submit(check_stream_url, url): url
                for url in check_urls
            }

            for future in as_completed(futures):
                url = futures[future]
                try:
                    status, detail = future.result()
                except Exception as exc:
                    status, detail = "bad", str(exc)

                results[url] = {
                    "status": status,
                    "detail": detail,
                }

        return results

    # İlk test
    results = run_check_pass(unique)

    # Sadece ilk testte başarısız olan kaynakları ikinci kez test et
    failed_urls = [
        url
        for url, result in results.items()
        if result.get("status") == "bad"
    ]

    if failed_urls:
        retry_results = run_check_pass(failed_urls)

        for url, retry_result in retry_results.items():
            first_result = results.get(url, {})

            if retry_result.get("status") == "ok":
                results[url] = {
                    "status": "ok",
                    "detail": (
                        "İlk test başarısızdı • ikinci test başarılı: "
                        + str(retry_result.get("detail", ""))
                    ),
                }
            else:
                results[url] = {
                    "status": "bad",
                    "detail": (
                        "İki testte de başarısız • "
                        + str(
                            retry_result.get(
                                "detail",
                                first_result.get("detail", "")
                            )
                        ),
                    ),
                }

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
                # Some upstream lists accidentally append attributes after the
                # channel title using malformed single quotes. Keep only the
                # actual title portion.
                match_name = re.search(
                    r'^(.*?)(?:\s+)(?:tvg-name|group-title|tvg-logo)=',
                    title,
                    re.I,
                )
                if match_name:
                    title = match_name.group(1).strip().strip("'\"")

            # Known malformed upstream spelling of TV 8.5.
            if re.match(r"^5\s*HD\.?tr'?$", title, re.I):
                title = "TV 8.5"

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
            if is_blocked_stream_url(line):
                pending = None
                current_meta = {}
                continue
            alternatives: list[str] = []
            for key, value in current_meta.items():
                if key.lower().startswith(("yedek", "backup")) and re.match(
                    r"^https?://", value, re.I
                ) and not is_blocked_stream_url(value):
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
                    "alternatives": alternatives[:MAX_QUALITY_CANDIDATES - 1],
                }
            )

            pending = None
            current_meta = {}

    return channels


def normalize_name(name: str) -> str:
    """Create a canonical key for matching channel variants."""
    value = unicodedata.normalize("NFKD", name)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.upper().replace("&", " AND ")

    # Remove quality/resolution decorations commonly appended by IPTV lists.
    value = re.sub(
        r"\b(?:2160P|1440P|1080P|720P|576P|480P|360P|240P|4K|8K|FHD|HD|SD|LIVE|CANLI)\b",
        " ",
        value,
    )
    # Country decorations such as "(Turkiye)" should not create a second channel.
    value = re.sub(r"\b(?:TURKIYE|TURKEY)\b", " ", value)

    value = re.sub(r"[^A-Z0-9]+", "", value)

    # Known aliases that are the same broadcaster/channel under different
    # labels in public M3U lists.
    aliases = {
        "NOWTV": "NOW",
        "NOW": "NOW",
    }
    return aliases.get(value, value)


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
            urls = [
                item for item in urls
                if re.match(r"^https?://", item, re.I)
                and not is_blocked_stream_url(item)
            ]

            if not urls:
                continue

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

                incoming_logo = str(channel.get("logo") or "")
                incoming_name = str(channel.get("name") or "")
                if incoming_logo and (
                    not target.get("logo")
                    or (
                        normalize_name(target.get("name", "")) == "NOW"
                        and incoming_name.strip().upper() in {"NOW TV", "NOW TV HD"}
                    )
                ):
                    target["logo"] = incoming_logo

                if (
                    normalize_name(target.get("name", "")) == "NOW"
                    and incoming_name.strip().upper() in {"NOW TV", "NOW TV HD"}
                ):
                    target["name"] = "NOW TV"

                current_group = str(target.get("group") or "Diğer")
                new_group = str(channel.get("group") or "Diğer")
                if current_group == "Diğer" and new_group != "Diğer":
                    target["group"] = new_group

            source_order += 1

            existing_urls = [str(target["url"])] + [
                str(item) for item in target["alternatives"]
            ]

            for url in urls:
                if url not in existing_urls and len(target["alternatives"]) < MAX_QUALITY_CANDIDATES - 1:
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
    """Fill logos and apply explicit preferred logos for key channels."""
    logo_index = fetch_turkey_logo_index()

    filled = 0
    for channel in channels:
        name = str(channel.get("name") or "").strip()
        preferred_logo = PREFERRED_CHANNEL_LOGOS.get(normalize_name(name))
        if preferred_logo:
            if channel.get("logo") != preferred_logo:
                channel["logo"] = preferred_logo
                filled += 1
            continue

        if str(channel.get("logo") or "").strip():
            continue
        alias_filename = next(
            (
                candidate
                for alias, candidate in LOGO_ALIASES.items()
                if normalize_name(alias) == normalize_name(name)
            ),
            None,
        )
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


def build_provider_trust(
    provider_urls: dict[str, set[str]],
    health_by_url: dict[str, dict[str, str]],
    quality: dict[str, dict[str, object]],
    previous: dict[str, object],
    checked_at: str,
) -> dict[str, dict[str, object]]:
    previous_providers = previous.get("providers", {}) if isinstance(previous, dict) else {}
    if not isinstance(previous_providers, dict):
        previous_providers = {}

    providers: dict[str, dict[str, object]] = {}
    for provider, urls in provider_urls.items():
        checked = [url for url in urls if url in health_by_url]
        healthy = [url for url in checked if health_by_url[url].get("status") == "ok"]
        failed = [url for url in checked if health_by_url[url].get("status") == "bad"]
        health_ratio = len(healthy) / max(1, len(checked))
        scores = [float(quality[url].get("score", 50) or 50) for url in checked if url in quality]
        avg_score = sum(scores) / len(scores) if scores else 50.0
        coverage = min(1.0, len(checked) / max(1, min(len(urls), 30)))
        current_score = round((health_ratio * 100) * 0.60 + avg_score * 0.30 + coverage * 100 * 0.10)

        old = previous_providers.get(provider, {}) if isinstance(previous_providers, dict) else {}
        old_score = float(old.get("score", 0) or 0) if isinstance(old, dict) else 0
        score = round(old_score * 0.65 + current_score * 0.35) if old_score else current_score
        label = (
            "Çok güvenilir" if score >= 85 else
            "Güvenilir" if score >= 70 else
            "Orta" if score >= 50 else
            "Zayıf"
        )
        providers[provider] = {
            "score": max(0, min(100, score)),
            "label": label,
            "checkedUrls": len(checked),
            "healthyUrls": len(healthy),
            "failedUrls": len(failed),
            "healthRatio": round(health_ratio, 3),
            "averageUrlScore": round(avg_score, 1),
            "coverage": round(coverage, 3),
            "urlCount": len(urls),
            "lastCheckedAt": checked_at,
            "active": bool(len(healthy) > 0 or not checked),
            "automatic": provider.startswith("auto:"),
        }
    return providers


def update_discovered_source_health(
    candidates: dict[str, object],
    health_by_url: dict[str, dict[str, str]],
    checked_at: str,
) -> dict[str, object]:
    document = load_json_object(DISCOVERY_PATH, {})
    entries = document.get("candidates", [])
    if not isinstance(entries, list):
        return document

    updated_entries = []
    for item in entries:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        if url not in candidates:
            updated_entries.append(item)
            continue
        urls = [str(value) for value in item.get("urls", []) if str(value).startswith(("http://", "https://"))]
        checked = [value for value in urls if value in health_by_url]
        healthy = [value for value in checked if health_by_url[value].get("status") == "ok"]
        failed = [value for value in checked if health_by_url[value].get("status") == "bad"]
        if len(checked) >= 5:
            health_score = round(len(healthy) / len(checked) * 100)
            item["healthScore"] = health_score
            item["healthyUrls"] = len(healthy)
            item["checkedUrls"] = len(checked)
            item["lastHealthAt"] = checked_at
            item["status"] = "active" if len(healthy) >= 3 and health_score >= 50 else "rejected"
            item["lastError"] = "" if item["status"] == "active" else f"Sağlık oranı düşük: {health_score}% ({len(healthy)}/{len(checked)})"
        updated_entries.append(item)

    updated_entries.sort(
        key=lambda item: (
            item.get("status") not in {"active", "trial"},
            -int(item.get("healthScore") or 0),
            -int(item.get("staticScore") or 0),
        )
    )
    document["updatedAt"] = checked_at
    document["candidates"] = updated_entries[:AUTO_SOURCE_MAX]
    document["activeAutoSources"] = sum(1 for item in document["candidates"] if item.get("status") == "active")
    DISCOVERY_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return document


def append_update_history(entry: dict[str, object]) -> None:
    document = load_json_object(HISTORY_PATH, {"version": 1, "retentionRuns": 180, "runs": []})
    runs = document.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    runs.append(entry)
    retention = max(30, int(document.get("retentionRuns", 180) or 180))
    document["version"] = 1
    document["retentionRuns"] = retention
    document["runs"] = runs[-retention:]
    HISTORY_PATH.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_m3u(channels: list[dict[str, object]], fetched_at: str) -> str:
    lines = [
        "#EXTM3U",
        "# KulakTV multi-source playlist",
        "# Sources: OnurEröz Türkiye + ByteFix Repairs + iptv-org Türkiye + discevisita + iptv-turk-tr + rideordie16/tv + qazim/IPTV + ilyswch/IPTV-TR",
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
    configured_sources = get_configured_sources()

    successful: list[tuple[str, str, list[dict[str, object]]]] = []
    failed: list[dict[str, str]] = []

    for source_name, source_url in configured_sources:
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
                "configuredSourceCount": len(configured_sources),
                "channelCount": 0,
                "sources": failed,
                "message": "No upstream source was available; last known-good playlist was kept.",
            }
        )
        append_update_history({
            "updatedAt": fetched_at,
            "status": "fetch_failed",
            "sourceCount": 0,
            "configuredSourceCount": len(configured_sources),
            "channelCount": 0,
            "health": {"checked": 0, "healthy": 0, "failed": 0},
            "message": "No upstream source was available; last known-good playlist was kept.",
        })
        print("No source succeeded. Keeping last known-good channels.m3u.")
        return 0

    provider_urls: dict[str, set[str]] = {}
    provider_names_by_url: dict[str, list[str]] = {}
    for source_name, _resolved_url, channels in successful:
        bucket = provider_urls.setdefault(source_name, set())
        for channel in channels:
            urls = [str(channel.get("url") or "")] + [str(value) for value in channel.get("alternatives", [])]
            for url in urls:
                if url.startswith(("http://", "https://")):
                    bucket.add(url)
                    provider_names_by_url.setdefault(url, [])
                    if source_name not in provider_names_by_url[url]:
                        provider_names_by_url[url].append(source_name)

    merged = merge_channels(successful)
    logos_filled = enrich_missing_logos(merged)
    print(f"Logo enrichment: {logos_filled} missing channel logos filled.")

    health_summary = {"checked": 0, "healthy": 0, "failed": 0}
    health_failures: list[dict[str, str]] = []
    source_quality_snapshot: list[tuple[str, str, dict[str, str]]] = []
    for channel in merged:
        for url, result in (channel.get("health") or {}).items():
            source_quality_snapshot.append((
                str(channel["name"]),
                str(url),
                {
                    "status": str(result.get("status") or "unknown"),
                    "detail": str(result.get("detail") or ""),
                },
            ))
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

    previous_source_quality = load_source_quality()
    health_by_url = {
        url: result
        for _channel, url, result in source_quality_snapshot
    }
    next_source_quality = update_source_quality(
        previous_source_quality.get("sources", previous_source_quality),
        source_quality_snapshot,
        fetched_at,
        provider_names_by_url,
    )
    discovery_candidates = load_json_object(DISCOVERY_PATH, {}).get("candidates", [])
    auto_url_map = {
        str(item.get("url")): item for item in discovery_candidates
        if isinstance(item, dict) and item.get("url")
    } if isinstance(discovery_candidates, list) else {}
    discovery_document = update_discovered_source_health(auto_url_map, health_by_url, fetched_at)
    provider_scores = build_provider_trust(
        provider_urls,
        health_by_url,
        next_source_quality,
        previous_source_quality,
        fetched_at,
    )
    save_source_quality(next_source_quality, fetched_at, provider_scores)

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
            "configuredSourceCount": len(configured_sources),
            "autoSourceCount": sum(1 for name, _url in configured_sources if name.startswith("auto:")),
            "sources": [
                {
                    "name": name,
                    "url": configured_url,
                    "resolvedUrl": final_url,
                    "channelCount": len(channels),
                    "status": "ok",
                    "trustScore": provider_scores.get(name, {}).get("score"),
                    "trustLabel": provider_scores.get(name, {}).get("label"),
                    "automatic": provider_scores.get(name, {}).get("automatic", name.startswith("auto:")),
                }
                for (name, final_url, channels) in successful
                for configured_name, configured_url in configured_sources
                if configured_name == name
            ]
            + failed,
            "logosFilled": logos_filled,
            "healthCheck": {
                "enabled": HEALTH_CHECK_ENABLED,
                "verification": "M3U8 manifest + at least one media segment",
                "checkedUrls": health_summary["checked"],
                "healthyUrls": health_summary["healthy"],
                "failedUrls": health_summary["failed"],
                "failures": health_failures,
                "ordering": "healthy-first, failed-last",
                "globalHealthDegraded": bool(removal_summary["degraded"]),
                "pendingRemoval": removal_summary["pendingRemoval"],
                "removedAfterTwoFailures": removal_summary["removed"],
            },
            "epg": load_json_object(EPG_STATUS_PATH, {}),
            "discovery": {
                "candidateCount": len(discovery_document.get("candidates", [])) if isinstance(discovery_document.get("candidates", []), list) else 0,
                "activeAutoSources": int(discovery_document.get("activeAutoSources", 0) or 0),
            },
            "message": (
                "Multi-source playlist merged successfully."
                if changed
                else "Merged playlist is already current."
            ),
        }
    )

    append_update_history({
        "updatedAt": fetched_at,
        "status": "updated" if changed else "current",
        "sourceCount": len(successful),
        "configuredSourceCount": len(configured_sources),
        "autoSourceCount": sum(1 for name, _url in configured_sources if name.startswith("auto:")),
        "channelCount": len(merged),
        "logosFilled": logos_filled,
        "health": {
            "checked": health_summary["checked"],
            "healthy": health_summary["healthy"],
            "failed": health_summary["failed"],
            "ratio": round(ratio, 3),
        },
        "providers": {
            name: int(data.get("score", 0) or 0)
            for name, data in provider_scores.items()
        },
        "epg": {
            "status": load_json_object(EPG_STATUS_PATH, {}).get("status"),
            "matchedChannels": load_json_object(EPG_STATUS_PATH, {}).get("matchedChannels", 0),
            "programmeCount": load_json_object(EPG_STATUS_PATH, {}).get("programmeCount", 0),
        },
        "discovery": {
            "candidateCount": len(discovery_document.get("candidates", [])) if isinstance(discovery_document.get("candidates", []), list) else 0,
            "activeAutoSources": int(discovery_document.get("activeAutoSources", 0) or 0),
        },
    })

    print(
        f"KulakTV: {len(merged)} unique channels merged from "
        f"{len(successful)}/{len(configured_sources)} sources; "
        f"playlist {'updated' if changed else 'already current'}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
