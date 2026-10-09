#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TELEMETRY_PATH = ROOT / "player-telemetry.json"
REPO = "sametkulak/kulaktv"
ISSUE_NUMBER = 1
MARKER = "KULAKTV-TELEMETRY v1"
MAX_PROCESSED_COMMENTS = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else default
    except Exception:
        return default


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def extract_event() -> tuple[str, dict[str, Any]] | None:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return None

    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}

    if int(issue.get("number") or 0) != ISSUE_NUMBER:
        return None

    comment_id = str(comment.get("id") or "").strip()
    body = str(comment.get("body") or "")
    if not comment_id or not body.startswith(MARKER):
        return None

    _, payload_text = body.split("\n", 1)
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        return None

    return comment_id, payload


def increment(mapping: dict[str, int], key: str) -> None:
    key = key or "unknown"
    mapping[key] = int(mapping.get(key, 0) or 0) + 1


def source_default(url: str, channel: str, host: str) -> dict[str, Any]:
    return {
        "url": url,
        "channel": channel,
        "host": host,
        "events": 0,
        "successes": 0,
        "failures": 0,
        "stalls": 0,
        "latencySumMs": 0,
        "latencyCount": 0,
        "lastEventAt": None,
        "devices": {},
        "browsers": {},
        "connections": {},
    }


def delete_comment(comment_id: str) -> None:
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("GITHUB_TOKEN yok; telemetry yorumu silinmeden bırakıldı.")
        return

    url = f"https://api.github.com/repos/{REPO}/issues/comments/{comment_id}"
    req = urllib.request.Request(
        url,
        method="DELETE",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            print(f"Telemetry yorumu temizlendi: HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        print(f"Telemetry yorumu silinemedi: HTTP {exc.code}")


def main() -> int:
    extracted = extract_event()
    if not extracted:
        print("Telemetry yorumu değil; işlem yok.")
        return 0

    comment_id, payload = extracted
    doc = load_json(
        TELEMETRY_PATH,
        {
            "version": 1,
            "updatedAt": None,
            "totalEvents": 0,
            "sessions": 0,
            "sources": {},
            "clients": {
                "devices": {},
                "browsers": {},
                "connections": {},
            },
            "processedCommentIds": [],
        },
    )

    processed = [str(x) for x in doc.get("processedCommentIds", [])]
    if comment_id in processed:
        print(f"Comment {comment_id} zaten işlendi.")
        return 0

    client = payload.get("client") or {}
    device = str(client.get("device") or "unknown")
    browser = str(client.get("browser") or "unknown")
    connection = str(client.get("connection") or "unknown")
    session_id = str(payload.get("sessionId") or "").strip()
    events = payload.get("events") or []

    if not isinstance(events, list):
        print("Telemetry events list değil; işlem yok.")
        return 0

    doc.setdefault("sources", {})
    doc.setdefault("clients", {"devices": {}, "browsers": {}, "connections": {}})
    clients = doc["clients"]

    increment(clients.setdefault("devices", {}), device)
    increment(clients.setdefault("browsers", {}), browser)
    increment(clients.setdefault("connections", {}), connection)

    known_sessions = [str(x) for x in doc.get("_knownSessionIds", [])]
    if session_id and session_id not in known_sessions:
        doc["sessions"] = int(doc.get("sessions", 0) or 0) + 1
        known_sessions.append(session_id)
        doc["_knownSessionIds"] = known_sessions[-5000:]

    accepted = 0
    sent_at = str(payload.get("sentAt") or now_iso())

    for event in events:
        if not isinstance(event, dict):
            continue

        url = str(event.get("url") or "").strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            continue

        channel = str(event.get("channel") or "unknown")
        host = str(event.get("host") or "")
        event_type = str(event.get("type") or "unknown").lower()
        source = doc["sources"].setdefault(
            url,
            source_default(url, channel, host),
        )

        source["channel"] = channel or source.get("channel") or "unknown"
        source["host"] = host or source.get("host") or ""
        source["events"] = int(source.get("events", 0) or 0) + 1
        source["lastEventAt"] = str(event.get("at") or sent_at)

        if event_type == "success":
            source["successes"] = int(source.get("successes", 0) or 0) + 1
        elif event_type == "failure":
            source["failures"] = int(source.get("failures", 0) or 0) + 1
        elif event_type == "stall":
            source["stalls"] = int(source.get("stalls", 0) or 0) + 1

        latency = event.get("latencyMs")
        if event_type == "success" and isinstance(latency, (int, float)) and latency > 0:
            source["latencySumMs"] = int(source.get("latencySumMs", 0) or 0) + int(latency)
            source["latencyCount"] = int(source.get("latencyCount", 0) or 0) + 1

        increment(source.setdefault("devices", {}), device)
        increment(source.setdefault("browsers", {}), browser)
        increment(source.setdefault("connections", {}), connection)
        accepted += 1

    doc["totalEvents"] = int(doc.get("totalEvents", 0) or 0) + accepted
    doc["updatedAt"] = sent_at
    processed.append(comment_id)
    doc["processedCommentIds"] = processed[-MAX_PROCESSED_COMMENTS:]

    save_json(TELEMETRY_PATH, doc)
    print(f"Telemetry işlendi: {accepted} event, comment={comment_id}")

    # Public inbox'taki ham yorumları otomatik temizle.
    delete_comment(comment_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
