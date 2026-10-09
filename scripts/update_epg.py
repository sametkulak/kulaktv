#!/usr/bin/env python3
"""Fetch the Turkish XMLTV guide and publish a compact JSON EPG for KulakTV."""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYLIST_PATH = ROOT / "channels.m3u"
EPG_PATH = ROOT / "epg.json"
STATUS_PATH = ROOT / "epg-status.json"

EPG_SOURCE_GZIP = "https://raw.githubusercontent.com/trology85/iptv-epg-turkey/main/epg/turksat_epg.xml.gz"
EPG_SOURCE_RAW = "https://raw.githubusercontent.com/trology85/iptv-epg-turkey/main/epg/turksat_epg.xml"
EPG_TIMEOUT = 30
EPG_WINDOW_HOURS = 72
EPG_PAST_GRACE_MINUTES = 90


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
    aliases = {"NOWTV": "NOW", "NOW": "NOW"}
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


def fetch_epg() -> tuple[bytes, str]:
    try:
        payload = fetch_bytes(EPG_SOURCE_GZIP)
        try:
            return gzip.decompress(payload), EPG_SOURCE_GZIP
        except OSError:
            return payload, EPG_SOURCE_GZIP
    except Exception as first_error:
        try:
            return fetch_bytes(EPG_SOURCE_RAW), EPG_SOURCE_RAW
        except Exception as second_error:
            raise RuntimeError(f"Gzip ve ham XML EPG kaynakları alınamadı: {first_error}; {second_error}")


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
        xml_bytes, source = fetch_epg()
        channels, programme_count = build_epg(xml_bytes, now)
        if len(channels) < 5 or programme_count < 20:
            raise RuntimeError(
                f"EPG verisi geçerli görünmüyor: {len(channels)} eşleşen kanal, {programme_count} program."
            )

        payload = {
            "version": 1,
            "updatedAt": fetched_at,
            "source": source,
            "windowHours": EPG_WINDOW_HOURS,
            "channels": channels,
        }
        EPG_PATH.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        save_status("updated", fetched_at, len(channels), programme_count, source)
        sync_pipeline_epg_status("updated", len(channels), programme_count)
        print(f"EPG güncellendi: {len(channels)} kanal / {programme_count} program")
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
                json.dumps({"version": 1, "updatedAt": None, "source": EPG_SOURCE_GZIP, "channels": {}}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        previous_channels = len((previous or {}).get("channels", {}))
        save_status("error", fetched_at, previous_channels, 0, EPG_SOURCE_GZIP, str(exc))
        sync_pipeline_epg_status("error", previous_channels, 0, str(exc))
        print(f"::warning::EPG güncellenemedi, son geçerli veri korunuyor: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
