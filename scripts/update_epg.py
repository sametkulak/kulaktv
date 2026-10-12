#!/usr/bin/env python3
"""Fetch the Turkish XMLTV guide and publish a compact JSON EPG for KulakTV."""

from __future__ import annotations

import gzip
import json
import re
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYLIST_PATH = ROOT / "channels.m3u"
EPG_PATH = ROOT / "epg.json"
STATUS_PATH = ROOT / "epg-status.json"

TURKSAT_JSON_BASE = "https://www.turksatkablo.com.tr/userUpload/EPG"

EPG_SOURCES = [
    (
        "https://iptv-org.github.io/epg/guides/tr/dsmart.com.tr.epg.xml.gz",
        "https://iptv-org.github.io/epg/guides/tr/dsmart.com.tr.epg.xml",
    ),
    (
        "https://iptv-org.github.io/epg/guides/tr/digiturk.com.tr.epg.xml.gz",
        "https://iptv-org.github.io/epg/guides/tr/digiturk.com.tr.epg.xml",
    ),
    (
        "https://dearbulut.github.io/iptv/epg/guide.xml.gz",
        "https://dearbulut.github.io/iptv/epg/guide.xml",
    ),
    (
        "https://epg.tvcdn.net/guide/tr-guide.xml",
        "https://epg.tvcdn.net/guide/tr-guide.xml",
    ),
    (
        "https://streams.uzunmuhalefet.com/epg/tr.xml",
        "https://streams.uzunmuhalefet.com/epg/tr.xml",
    ),
    (
        "https://raw.githubusercontent.com/trology85/iptv-epg-turkey/main/epg/turksat_epg.xml.gz",
        "https://raw.githubusercontent.com/trology85/iptv-epg-turkey/main/epg/turksat_epg.xml",
    ),
]
EPG_TIMEOUT = 30
EPG_WINDOW_HOURS = 72
EPG_PAST_GRACE_MINUTES = 90


# Türksat'ın resmi EPG JSON uç noktası GitHub-hosted runner üzerinde sertifika
# zinciri doğrulama hatası verebiliyor. TLS doğrulaması varsayılan olarak açık
# kalır; yalnızca bu resmi host/path için, yanıt yapısı ayrıca doğrulanarak
# dar kapsamlı bir ikinci deneme yapılır.
TURKSAT_INSECURE_FALLBACK = True


def is_turksat_json_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return (
            host == "www.turksatkablo.com.tr"
            and parsed.path.startswith("/userUpload/EPG/")
            and parsed.path.endswith(".json")
            and parsed.query == ""
        )
    except Exception:
        return False



def normalize(value: str) -> str:
    value = str(value or "").strip().upper()
    value = value.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G")
    value = value.replace("Ü", "U").replace("Ö", "O").replace("Ç", "C")
    value = re.sub(
        r"\b(?:2160P|1440P|1080P|720P|576P|480P|360P|240P|4K|8K|FHD|HD|SD|LIVE|CANLI)\b",
        " ",
        value,
    )
    value = re.sub(r"\b(?:TURKIYE|TURKEY)\b", " ", value)
    value = re.sub(r"[^A-Z0-9]+", "", value)
    aliases = {
        "NOWTV": "NOW",
        "NOW": "NOW",
        "FOX": "NOW",
        "FOXTV": "NOW",
        "FOXTURKIYE": "NOW",
        "SHOW": "SHOWTV",
        "SHOWTV": "SHOWTV",
        "SHOWTVHD": "SHOWTV",
        "SHOWTVHDTR": "SHOWTV",
        "360TV": "360",
        "24TV": "24",
        "AHABERHD": "AHABER",
        "SOZCU": "SOZCUTV",
        "SOZCUTV": "SOZCUTV",
        "HABERTURK": "HABERTURKTV",
        "HABERTURKTV": "HABERTURKTV",
        "STARTV": "STAR",
        "STAR": "STAR",
    }
    return aliases.get(value, value)


def clean_id(value: str) -> str:
    value = str(value or "").strip().upper()
    value = value.split("@", 1)[0]
    value = value.split(".", 1)[0]
    value = re.sub(r"[^A-Z0-9]+", "", value)
    return {"NOWTV": "NOW"}.get(value, value)


def read_playlist_channels() -> tuple[dict[str, dict[str, str]], set[str]]:
    by_name: dict[str, dict[str, str]] = {}
    by_id: dict[str, str] = {}
    lines = PLAYLIST_PATH.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("#EXTINF:"):
            continue
        comma = line.find(",")
        if comma < 0:
            continue
        title = line[comma + 1 :].strip()
        attrs = {
            m.group(1): m.group(2)
            for m in re.finditer(r'([\w-]+)="([^"]*)"', line[:comma])
        }
        key = normalize(title)
        if not key:
            continue
        record = {"key": key, "name": title, "tvg_id": attrs.get("tvg-id", "")}
        by_name.setdefault(key, record)
        channel_id = clean_id(record["tvg_id"])
        if channel_id:
            by_id.setdefault(channel_id, key)
    return by_name | {k: v for k, v in by_name.items()}, set(by_id)


def read_playlist_map() -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    by_name: dict[str, dict[str, str]] = {}
    by_id: dict[str, str] = {}
    lines = PLAYLIST_PATH.read_text(encoding="utf-8").splitlines()
    for line in lines:
        if not line.startswith("#EXTINF:"):
            continue
        comma = line.find(",")
        if comma < 0:
            continue
        title = line[comma + 1 :].strip()
        attrs = {
            m.group(1): m.group(2)
            for m in re.finditer(r'([\w-]+)="([^"]*)"', line[:comma])
        }
        key = normalize(title)
        if not key:
            continue
        by_name.setdefault(key, {"key": key, "name": title, "tvg_id": attrs.get("tvg-id", "")})
        tvg = clean_id(attrs.get("tvg-id", ""))
        if tvg:
            by_id.setdefault(tvg, key)
    return by_name, by_id


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "KulakTV-EPG-Updater/1.0",
            "Accept": "application/gzip,application/xml,text/xml,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=EPG_TIMEOUT) as response:
        return response.read()


def fetch_turksat_json() -> list[tuple[dict[str, object], datetime, str]]:
    turkey_tz = timezone(timedelta(hours=3))
    today_tr = datetime.now(timezone.utc).astimezone(turkey_tz)
    results: list[tuple[dict[str, object], datetime, str]] = []
    errors: list[str] = []

    # Bugün ve yarının resmi Türksat JSON'unu dene. Yarının dosyası yoksa
    # mevcut günün verisi yine kullanılabilir.
    for day_offset in (0, 1):
        target = today_tr + timedelta(days=day_offset)
        day_url = f"{TURKSAT_JSON_BASE}/{target.day}.json"
        try:
            request = urllib.request.Request(
                day_url,
                headers={
                    "User-Agent": "Mozilla/5.0 KulakTV-EPG-Updater/1.1",
                    "Referer": "https://www.turksatkablo.com.tr/yayin-akisi.aspx",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=EPG_TIMEOUT,
                ) as response:
                    payload = response.read()
            except ssl.SSLCertVerificationError:
                if not TURKSAT_INSECURE_FALLBACK or not is_turksat_json_url(day_url):
                    raise
                print(
                    "::warning::Türksat EPG HTTPS sertifikası doğrulanamadı; "
                    "yalnızca resmi Türksat EPG JSON endpoint'i için doğrulama "
                    "kapalı yedek deneme yapılıyor."
                )
                insecure_context = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    request,
                    timeout=EPG_TIMEOUT,
                    context=insecure_context,
                ) as response:
                    payload = response.read()
            except urllib.error.URLError as exc:
                reason = getattr(exc, "reason", None)
                if not (
                    TURKSAT_INSECURE_FALLBACK
                    and is_turksat_json_url(day_url)
                    and "CERTIFICATE_VERIFY_FAILED" in str(reason)
                ):
                    raise
                print(
                    "::warning::Türksat EPG HTTPS sertifikası doğrulanamadı; "
                    "yalnızca resmi Türksat EPG JSON endpoint'i için doğrulama "
                    "kapalı yedek deneme yapılıyor."
                )
                insecure_context = ssl._create_unverified_context()
                with urllib.request.urlopen(
                    request,
                    timeout=EPG_TIMEOUT,
                    context=insecure_context,
                ) as response:
                    payload = response.read()

            data = json.loads(payload.decode("utf-8-sig"))
            raw_channels = data.get("k") if isinstance(data, dict) else None
            if not isinstance(raw_channels, list) or not raw_channels:
                raise RuntimeError("Türksat EPG JSON'unda geçerli kanal listesi yok.")
            valid_channels = sum(
                1
                for item in raw_channels
                if isinstance(item, dict) and str(item.get("n") or "").strip()
            )
            if valid_channels < 5:
                raise RuntimeError(
                    f"Türksat EPG JSON'u beklenenden farklı: {valid_channels} geçerli kanal."
                )
            results.append((data, target, day_url))
        except Exception as exc:
            errors.append(f"{day_url}: {exc}")

    if not results:
        raise RuntimeError("Türksat güncel EPG JSON'u alınamadı: " + " | ".join(errors))

    return results
def program_title_key(title: object) -> str:
    value = str(title or "").strip().lower()
    value = re.sub(r"\s+", " ", value)
    return value


def append_epg_program(programs: list[dict[str, object]], item: dict[str, object]) -> bool:
    """Append one program unless it overlaps an existing schedule entry.

    Türksat verisi ilk sırada işlenir. Sonraki XMLTV kaynakları aynı zaman
    aralığını kapsayan bir kayıt gönderirse mevcut kayıt korunur. Yalnızca
    mevcut kayıt placeholder ("-") ise daha anlamlı başlıkla değiştirilebilir.
    """
    start = item.get("start")
    stop = item.get("stop")
    try:
        start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        stop_dt = datetime.fromisoformat(str(stop).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False

    title_key = program_title_key(item.get("title"))
    placeholder = title_key in {"", "-" ,"program bilgisi yok"}

    for index, existing in enumerate(programs):
        try:
            existing_start = datetime.fromisoformat(str(existing.get("start")).replace("Z", "+00:00"))
            existing_stop = datetime.fromisoformat(str(existing.get("stop")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue

        if existing.get("start") == item.get("start") and title_key == program_title_key(existing.get("title")):
            return False

        overlap_start = max(start_dt, existing_start)
        overlap_stop = min(stop_dt, existing_stop)
        overlap_seconds = max(0.0, (overlap_stop - overlap_start).total_seconds())
        new_duration = max(1.0, (stop_dt - start_dt).total_seconds())
        existing_duration = max(1.0, (existing_stop - existing_start).total_seconds())
        overlap_ratio = overlap_seconds / min(new_duration, existing_duration)

        if overlap_ratio >= 0.60:
            existing_placeholder = program_title_key(existing.get("title")) in {"", "-", "program bilgisi yok"}
            if existing_placeholder and not placeholder:
                programs[index] = item
                return True
            return False

    programs.append(item)
    return True

def build_epg_from_turksat(
    data: dict[str, object],
    actual_date: datetime,
) -> tuple[dict[str, dict[str, object]], int]:
    playlist_by_name, playlist_by_id = read_playlist_map()
    result: dict[str, dict[str, object]] = {}
    programme_count = 0

    raw_channels = data.get("k", [])
    if not isinstance(raw_channels, list):
        return result, 0

    for channel in raw_channels:
        if not isinstance(channel, dict):
            continue
        channel_name = str(channel.get("n") or "").strip()
        key = normalize(channel_name)
        if not key:
            continue

        if key not in playlist_by_name:
            # Bazı yayın akışı adlarında "TV" ve çözünürlük farkları oluyor.
            key = next(
                (candidate for candidate in playlist_by_name if normalize(candidate) == normalize(channel_name)),
                key,
            )

        if key not in playlist_by_name:
            continue

        bucket = result.setdefault(
            key,
            {
                "name": playlist_by_name[key].get("name", channel_name),
                "programs": [],
            },
        )
        programs = bucket["programs"]
        raw_programs = channel.get("p", [])
        if not isinstance(programs, list) or not isinstance(raw_programs, list):
            continue

        for program in raw_programs:
            if not isinstance(program, dict):
                continue
            start_text = str(program.get("c") or "").strip()
            stop_text = str(program.get("d") or "").strip()
            title = str(program.get("b") or "").strip() or "Program bilgisi yok"
            if not re.fullmatch(r"\d{1,2}:\d{2}", start_text) or not re.fullmatch(r"\d{1,2}:\d{2}", stop_text):
                continue

            try:
                sh, sm = map(int, start_text.split(":"))
                eh, em = map(int, stop_text.split(":"))
                start_local = actual_date.replace(hour=sh, minute=sm, second=0, microsecond=0)
                stop_local = actual_date.replace(hour=eh, minute=em, second=0, microsecond=0)
                if stop_local <= start_local:
                    stop_local += timedelta(days=1)

                start = start_local.astimezone(timezone.utc)
                stop = stop_local.astimezone(timezone.utc)
            except ValueError:
                continue

            item = {
                "start": start.isoformat().replace("+00:00", "Z"),
                "stop": stop.isoformat().replace("+00:00", "Z"),
                "title": title,
            }
            if len(programs) < 40 and append_epg_program(programs, item):
                programme_count += 1

    for bucket in result.values():
        programs = bucket.get("programs")
        if isinstance(programs, list):
            programs.sort(key=lambda x: x.get("start", ""))

    return result, programme_count


def fetch_epg() -> list[tuple[bytes, str]]:
    errors: list[str] = []
    results: list[tuple[bytes, str]] = []

    for xml_source in EPG_SOURCES:
        gzip_url, raw_url = xml_source
        try:
            payload = fetch_bytes(gzip_url)
            try:
                xml_bytes = gzip.decompress(payload)
            except OSError:
                xml_bytes = payload
            if b"<tv" in xml_bytes[:2000]:
                results.append((xml_bytes, gzip_url))
                continue
            raise RuntimeError("Gzip yanıtı XMLTV olarak çözülemedi.")
        except Exception as first_error:
            try:
                xml_bytes = fetch_bytes(raw_url)
                if b"<tv" not in xml_bytes[:2000]:
                    raise RuntimeError("Ham yanıt XMLTV değil.")
                results.append((xml_bytes, raw_url))
            except Exception as second_error:
                errors.append(f"{gzip_url}: {first_error}; {second_error}")

    if not results:
        raise RuntimeError("XMLTV EPG kaynaklarının hiçbiri alınamadı: " + " | ".join(errors))

    return results

def parse_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    match = re.match(r"^(\d{14})(?:\s*([+-]\d{4}|Z))?$", raw)
    if not match:
        return None
    try:
        base = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    offset = match.group(2)
    if not offset or offset == "Z":
        return base.replace(tzinfo=timezone.utc)
    sign = 1 if offset[0] == "+" else -1
    hours = int(offset[1:3])
    minutes = int(offset[3:5])
    tz = timezone(sign * timedelta(hours=hours, minutes=minutes))
    return base.replace(tzinfo=tz).astimezone(timezone.utc)


def text_of(parent: ET.Element, tag: str) -> str:
    node = parent.find(tag)
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def map_epg_channels(root: ET.Element, playlist_by_name: dict[str, dict[str, str]], playlist_by_id: dict[str, str]) -> dict[str, str]:
    channel_map: dict[str, str] = {}
    for node in root.findall("channel"):
        epg_id = str(node.attrib.get("id") or "")
        names = [str(node.text or "").strip() for node in node.findall("display-name") if (node.text or "").strip()]
        mapped = None
        for display_name in names:
            key = normalize(display_name)
            if key in playlist_by_name:
                mapped = key
                break
        if mapped is None:
            mapped = playlist_by_id.get(clean_id(epg_id))
        if mapped:
            channel_map[epg_id] = mapped
    return channel_map


def build_epg(xml_bytes: bytes, now: datetime) -> tuple[dict[str, dict[str, object]], int]:
    root = ET.fromstring(xml_bytes)
    playlist_by_name, playlist_by_id = read_playlist_map()
    channel_map = map_epg_channels(root, playlist_by_name, playlist_by_id)
    window_start = now - timedelta(minutes=EPG_PAST_GRACE_MINUTES)
    window_end = now + timedelta(hours=EPG_WINDOW_HOURS)

    result: dict[str, dict[str, object]] = {}
    programme_count = 0

    for programme in root.findall("programme"):
        source_channel = str(programme.attrib.get("channel") or "")
        target_key = channel_map.get(source_channel)
        if not target_key:
            continue

        start = parse_timestamp(programme.attrib.get("start", ""))
        stop = parse_timestamp(programme.attrib.get("stop", ""))
        if not start or not stop or stop <= window_start or start >= window_end:
            continue

        title = text_of(programme, "title") or "Program bilgisi yok"
        desc = text_of(programme, "desc")
        category = text_of(programme, "category")
        item = {
            "start": start.isoformat().replace("+00:00", "Z"),
            "stop": stop.isoformat().replace("+00:00", "Z"),
            "title": title,
        }
        if desc:
            item["desc"] = desc
        if category:
            item["category"] = category

        bucket = result.setdefault(
            target_key,
            {
                "name": playlist_by_name.get(target_key, {}).get("name", target_key),
                "programs": [],
            },
        )
        programs = bucket["programs"]
        if isinstance(programs, list) and all(
            not (existing.get("start") == item["start"] and existing.get("title") == item["title"])
            for existing in programs
            if isinstance(existing, dict)
        ):
            if len(programs) < 40:
                programs.append(item)
                programme_count += 1

    for bucket in result.values():
        programs = bucket["programs"]
        if isinstance(programs, list):
            programs.sort(key=lambda x: x.get("start", ""))

    return result, programme_count


def sync_pipeline_epg_status(status: str, matched_channels: int, programme_count: int, message: str = "") -> None:
    """After EPG finishes, sync its result into the latest pipeline status/history."""
    status_path = ROOT / "update-status.json"
    history_path = ROOT / "update-history.json"

    if status_path.exists():
        try:
            payload = json.loads(status_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                epg = payload.get("epg")
                if not isinstance(epg, dict):
                    epg = {}
                epg.update({
                    "version": 1,
                    "status": status,
                    "updatedAt": payload.get("updatedAt") or datetime.now(timezone.utc).isoformat(),
                    "matchedChannels": matched_channels,
                    "programmeCount": programme_count,
                })
                if message:
                    epg["message"] = message
                payload["epg"] = epg
                status_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:
            print(f"::warning::update-status.json EPG alanı senkronize edilemedi: {exc}")

    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            runs = history.get("runs")
            if isinstance(runs, list) and runs:
                latest = runs[-1]
                if isinstance(latest, dict):
                    epg = latest.get("epg")
                    if not isinstance(epg, dict):
                        epg = {}
                    epg.update({
                        "status": status,
                        "matchedChannels": matched_channels,
                        "programmeCount": programme_count,
                    })
                    if message:
                        epg["message"] = message
                    latest["epg"] = epg
                    history_path.write_text(
                        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8",
                    )
        except Exception as exc:
            print(f"::warning::update-history.json EPG alanı senkronize edilemedi: {exc}")


def save_status(status: str, fetched_at: str, matched_channels: int, programme_count: int, source: str, message: str = "") -> None:
    payload = {
        "version": 1,
        "status": status,
        "updatedAt": fetched_at,
        "sourceUrl": source,
        "matchedChannels": matched_channels,
        "programmeCount": programme_count,
    }
    if message:
        payload["message"] = message
    STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    now = datetime.now(timezone.utc)
    fetched_at = now.isoformat()

    try:
        if not PLAYLIST_PATH.exists():
            raise RuntimeError("channels.m3u bulunamadı.")

        merged_channels: dict[str, dict[str, object]] = {}
        source_names: list[str] = []
        total_programme_count = 0

        try:
            turksat_items = fetch_turksat_json()
            for data, actual_date, source in turksat_items:
                channels, programme_count = build_epg_from_turksat(data, actual_date)
                source_names.append(source)
                total_programme_count += programme_count
                print(
                    f"Türksat EPG alındı: {source} / "
                    f"{len(channels)} kanal / {programme_count} program"
                )
                for key, bucket in channels.items():
                    target = merged_channels.setdefault(
                        key, {"name": bucket.get("name", key), "programs": []}
                    )
                    target_programs = target["programs"]
                    source_programs = bucket.get("programs", [])
                    if not isinstance(target_programs, list) or not isinstance(source_programs, list):
                        continue
                    for item in source_programs:
                        if any(
                            isinstance(existing, dict)
                            and existing.get("start") == item.get("start")
                            and existing.get("title") == item.get("title")
                            for existing in target_programs
                        ):
                            continue
                        if len(target_programs) < 40:
                            target_programs.append(item)
        except Exception as exc:
            print(f"::warning::Doğrudan Türksat EPG alınamadı, XMLTV kaynaklarına geçiliyor: {exc}")

        fetched_sources = fetch_epg()

        for xml_bytes, source in fetched_sources:
            channels, programme_count = build_epg(xml_bytes, now)
            source_names.append(source)
            total_programme_count += programme_count

            for key, bucket in channels.items():
                target = merged_channels.setdefault(
                    key,
                    {"name": bucket.get("name", key), "programs": []},
                )
                target_programs = target["programs"]
                source_programs = bucket.get("programs", [])
                if not isinstance(target_programs, list) or not isinstance(source_programs, list):
                    continue

                for item in source_programs:
                    if not isinstance(item, dict):
                        continue
                    if len(target_programs) < 40:
                        append_epg_program(target_programs, item)

        for bucket in merged_channels.values():
            programs = bucket.get("programs")
            if isinstance(programs, list):
                programs.sort(key=lambda x: x.get("start", ""))

        merged_programme_count = sum(
            len(v.get("programs", []))
            for v in merged_channels.values()
            if isinstance(v, dict)
        )

        if len(merged_channels) < 5 or merged_programme_count < 20:
            raise RuntimeError(
                f"EPG verisi geçerli görünmüyor: {len(merged_channels)} eşleşen kanal, "
                f"{merged_programme_count} program."
            )

        payload = {
            "version": 1,
            "updatedAt": fetched_at,
            "source": source_names[0] if len(source_names) == 1 else source_names,
            "windowHours": EPG_WINDOW_HOURS,
            "channels": merged_channels,
        }
        EPG_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        save_status(
            "updated",
            fetched_at,
            len(merged_channels),
            merged_programme_count,
            source_names[0] if len(source_names) == 1 else ",".join(source_names),
        )
        sync_pipeline_epg_status(
            "updated",
            len(merged_channels),
            merged_programme_count,
        )
        print(
            f"EPG güncellendi: {len(merged_channels)} kanal / "
            f"{merged_programme_count} program / {len(source_names)} kaynak"
        )
        return 0
    except Exception as exc:
        previous = None
        if EPG_PATH.exists():
            try:
                previous = json.loads(EPG_PATH.read_text(encoding="utf-8"))
            except Exception:
                previous = None
        if not previous:
            EPG_PATH.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updatedAt": None,
                        "source": EPG_SOURCES,
                        "channels": {},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        previous_channels = len((previous or {}).get("channels", {}))
        save_status(
            "error",
            fetched_at,
            previous_channels,
            0,
            EPG_SOURCES[0][0],
            str(exc),
        )
        sync_pipeline_epg_status(
            "error",
            previous_channels,
            0,
            str(exc),
        )
        print(f"::warning::EPG güncellenemedi, son geçerli veri korunuyor: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
