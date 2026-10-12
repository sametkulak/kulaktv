#!/usr/bin/env python3
"""Validate KulakTV's automated channel and EPG pipeline outputs."""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHANNEL_STATUS_PATH = ROOT / "update-status.json"
EPG_STATUS_PATH = ROOT / "epg-status.json"
EPG_PATH = ROOT / "epg.json"
PLAYLIST_PATH = ROOT / "channels.m3u"
SOURCE_QUALITY_PATH = ROOT / "source-quality.json"
HISTORY_PATH = ROOT / "update-history.json"

MAX_CHANNEL_STATUS_AGE_HOURS = 28
MAX_EPG_STATUS_AGE_HOURS = 8
MIN_SOURCE_SUCCESS_RATIO = 0.60
MIN_HEALTH_RATIO = 0.20
MIN_CHANNELS = 10
MIN_EPG_CHANNELS = 10
MIN_EPG_PROGRAMS = 100

REQUIRED_CHANNELS = (
    "ATV",
    "KANAL D",
    "STAR TV",
    "TRT 1",
    "SHOW TV",
    "NOW",
    "TV8",
)

OBVIOUS_NON_TV_RE = re.compile(
    r"\b(?:RADYO|RADIO|PODCAST|AUDIO|WEBCAM|CAMERA|IP\s*CAM|ADULT|XXX|PORN)\b",
    re.IGNORECASE,
)


def load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        raise RuntimeError(f"Gerekli dosya bulunamadı: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"{path.name} geçersiz JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} JSON nesnesi değil.")
    return value


def parse_timestamp(value: object, label: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError(f"{label} güncelleme zamanı yok.")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError(f"{label} güncelleme zamanı geçersiz: {raw}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_hours(timestamp: datetime) -> float:
    return (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600


def normalize(value: object) -> str:
    text = str(value or "").strip().upper()
    text = (
        text.replace("İ", "I")
        .replace("Ş", "S")
        .replace("Ğ", "G")
        .replace("Ü", "U")
        .replace("Ö", "O")
        .replace("Ç", "C")
    )
    text = re.sub(
        r"\b(?:2160P|1440P|1080P|720P|576P|480P|360P|240P|4K|8K|FHD|HD|SD|LIVE|CANLI)\b",
        " ",
        text,
    )
    text = re.sub(r"\b(?:TURKIYE|TURKEY)\b", " ", text)
    return re.sub(r"[^A-Z0-9]+", "", text)


def check_channel_pipeline(status: dict[str, object]) -> list[str]:
    problems: list[str] = []

    status_name = str(status.get("status") or "")
    if status_name == "fetch_failed":
        problems.append("Son kanal güncellemesi fetch_failed durumunda.")
    elif status_name not in {"updated", "current"}:
        problems.append(f"Kanal güncelleme durumu beklenmiyor: {status_name or 'boş'}.")

    updated_at = parse_timestamp(status.get("updatedAt"), "Kanal")
    channel_age = age_hours(updated_at)
    if channel_age > MAX_CHANNEL_STATUS_AGE_HOURS:
        problems.append(f"Kanal verisi çok eski: {channel_age:.1f} saat.")

    configured = int(status.get("configuredSourceCount", 0) or 0)
    active = int(status.get("sourceCount", 0) or 0)
    if configured:
        source_ratio = active / configured
        if source_ratio < MIN_SOURCE_SUCCESS_RATIO:
            problems.append(
                f"Kaynak başarı oranı düşük: {active}/{configured} ({source_ratio:.0%})."
            )

    channel_count = int(status.get("channelCount", 0) or 0)
    if channel_count < MIN_CHANNELS:
        problems.append(f"Kanal sayısı beklenenden düşük: {channel_count}.")

    health = status.get("healthCheck")
    if not isinstance(health, dict):
        problems.append("healthCheck alanı eksik.")
    else:
        checked = int(health.get("checkedUrls", 0) or 0)
        healthy = int(health.get("healthyUrls", 0) or 0)
        if checked <= 0:
            problems.append("Hiçbir yayın URL'si health-check edilmemiş.")
        else:
            ratio = healthy / checked
            if ratio < MIN_HEALTH_RATIO:
                problems.append(
                    f"Global yayın sağlığı kritik: {healthy}/{checked} ({ratio:.0%})."
                )
        if "pendingRemoval" not in health or "removedAfterTwoFailures" not in health:
            problems.append("Health policy özet alanları eksik.")

    changes = status.get("changes")
    if isinstance(changes, dict):
        added = int(changes.get("addedCount", 0) or 0)
        removed = int(changes.get("removedCount", 0) or 0)
        if added > max(20, channel_count):
            problems.append(f"Anormal kanal ekleme: {added}.")
        if removed > max(20, channel_count):
            problems.append(f"Anormal kanal silme: {removed}.")

    return problems


def check_required_channels() -> list[str]:
    if not PLAYLIST_PATH.exists():
        return ["channels.m3u bulunamadı."]

    text = PLAYLIST_PATH.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for line in text.splitlines():
        if not line.startswith("#EXTINF:"):
            continue
        comma = line.find(",")
        if comma >= 0:
            names.add(normalize(line[comma + 1 :]))

    problems: list[str] = []
    missing = [name for name in REQUIRED_CHANNELS if normalize(name) not in names]
    if missing:
        problems.append("Ana kanallar eksik: " + ", ".join(missing))

    obvious_non_tv = []
    for name in names:
        if OBVIOUS_NON_TV_RE.search(name):
            obvious_non_tv.append(name)
    if obvious_non_tv:
        problems.append(
            "M3U'da açıkça TV dışı isimler bulundu: "
            + ", ".join(sorted(obvious_non_tv)[:10])
        )

    return problems


def check_filter_metadata(status: dict[str, object]) -> list[str]:
    problems: list[str] = []
    sources = status.get("sources")
    if not isinstance(sources, list):
        return ["Kaynak özeti liste değil."]

    required_filtered = {"UzunMuhalefet Türkiye", "dearbulut Türkiye"}
    seen_filtered: set[str] = set()

    for source in sources:
        if not isinstance(source, dict):
            continue
        name = str(source.get("name") or "")
        if name not in required_filtered:
            continue
        seen_filtered.add(name)
        if source.get("filter") != "Turkish TV only: radio/podcast/webcam/adult excluded":
            problems.append(f"{name} için Türk TV filtresi işaretlenmemiş.")
        if "filteredOutCount" not in source:
            problems.append(f"{name} için filteredOutCount eksik.")

    missing = required_filtered - seen_filtered
    if missing:
        problems.append("Filtrelenen kaynak özeti eksik: " + ", ".join(sorted(missing)))

    return problems


def check_epg_pipeline(status: dict[str, object], epg_status: dict[str, object], epg: dict[str, object]) -> list[str]:
    problems: list[str] = []

    epg_state = str(epg_status.get("status") or "")
    if epg_state != "updated":
        problems.append(f"EPG durumu güncel değil: {epg_state or 'boş'}.")

    updated_at = parse_timestamp(epg_status.get("updatedAt"), "EPG")
    epg_age = age_hours(updated_at)
    if epg_age > MAX_EPG_STATUS_AGE_HOURS:
        problems.append(f"EPG verisi çok eski: {epg_age:.1f} saat.")

    channels = epg.get("channels")
    if not isinstance(channels, dict):
        problems.append("epg.json channels alanı geçersiz.")
        return problems

    channel_count = len(channels)
    program_count = sum(
        len(value.get("programs", []))
        for value in channels.values()
        if isinstance(value, dict) and isinstance(value.get("programs"), list)
    )
    if channel_count < MIN_EPG_CHANNELS:
        problems.append(f"EPG kanal sayısı beklenenden düşük: {channel_count}.")
    if program_count < MIN_EPG_PROGRAMS:
        problems.append(f"EPG program sayısı beklenenden düşük: {program_count}.")

    if int(epg_status.get("matchedChannels", 0) or 0) != channel_count:
        problems.append(
            "epg-status.json matchedChannels ile epg.json kanal sayısı uyuşmuyor."
        )
    if int(epg_status.get("programmeCount", 0) or 0) != program_count:
        problems.append(
            "epg-status.json programmeCount ile epg.json program sayısı uyuşmuyor."
        )

    normalized_epg_names = {
        normalize(value.get("name") or key)
        for key, value in channels.items()
        if isinstance(value, dict)
    }
    missing = [
        name for name in REQUIRED_CHANNELS
        if normalize(name) not in normalized_epg_names
    ]
    # EPG kaynağının kapsamı daha dar olabilir. En az yarısının bulunması
    # beklenir; tam kanal listesi eşleşmesini zorlamıyoruz.
    if len(REQUIRED_CHANNELS) - len(missing) < 4:
        problems.append(
            "Ana kanal EPG kapsamı çok düşük: "
            f"{len(REQUIRED_CHANNELS) - len(missing)}/{len(REQUIRED_CHANNELS)}."
        )

    source = epg.get("source")
    if not source:
        problems.append("EPG source alanı boş.")

    return problems


def check_source_quality() -> list[str]:
    quality = load_json(SOURCE_QUALITY_PATH)
    sources = quality.get("sources")
    providers = quality.get("providers")
    problems: list[str] = []
    if not isinstance(sources, dict) or not sources:
        problems.append("source-quality.json sources alanı boş/geçersiz.")
    if not isinstance(providers, dict) or not providers:
        problems.append("source-quality.json providers alanı boş/geçersiz.")
    return problems


def check_history() -> list[str]:
    history = load_json(HISTORY_PATH)
    runs = history.get("runs")
    if not isinstance(runs, list) or not runs:
        return ["update-history.json içinde başarılı çalışma kaydı yok."]
    latest = runs[-1]
    if not isinstance(latest, dict):
        return ["update-history.json son kayıt geçersiz."]
    return []


def main() -> int:
    status = load_json(CHANNEL_STATUS_PATH)
    epg_status = load_json(EPG_STATUS_PATH)
    epg = load_json(EPG_PATH)

    problems = []
    problems.extend(check_channel_pipeline(status))
    problems.extend(check_required_channels())
    problems.extend(check_filter_metadata(status))
    problems.extend(check_epg_pipeline(status, epg_status, epg))
    problems.extend(check_source_quality())
    problems.extend(check_history())

    print("KulakTV otomasyon watchdog")
    print(f"Kanal: {status.get('channelCount', 0)} kanal / {status.get('sourceCount', 0)}/{status.get('configuredSourceCount', 0)} kaynak")
    health = status.get("healthCheck", {})
    if isinstance(health, dict):
        print(f"Health: {health.get('healthyUrls', 0)}/{health.get('checkedUrls', 0)} URL sağlıklı")
    print(
        f"EPG: {epg_status.get('matchedChannels', 0)} kanal / "
        f"{epg_status.get('programmeCount', 0)} program"
    )

    if problems:
        print("\nWATCHDOG FAIL:")
        for problem in problems:
            print(f"- {problem}")
        return 1

    print("\nWATCHDOG PASS: otomatik kanal + health + filtre + EPG akışı normal.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
