#!/usr/bin/env python3
"""Discover public Turkish M3U sources on GitHub and maintain a small trial pool."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from update_channels import SOURCES, normalize_name, parse_m3u

ROOT = Path(__file__).resolve().parents[1]
PLAYLIST_PATH = ROOT / "channels.m3u"
STATE_PATH = ROOT / "discovered-sources.json"

SEARCH_QUERIES = [
    "iptv m3u",
    "turk iptv",
    "turkey iptv",
    "turkish tv",
    "m3u turkey",
    "tr.m3u",
]
MAX_RESULTS_PER_QUERY = 20
MAX_REPOSITORIES = 30
MAX_PLAYLISTS_PER_REPO = 3
MAX_CANDIDATES = 12
MIN_CHANNELS = 10
MIN_UNIQUE_URLS = 5
MIN_NEW_URL_RATIO = 0.15
MIN_AUTO_SCORE = 70
FETCH_TIMEOUT = 18
MAX_BODY = 3 * 1024 * 1024

DISCOVERY_SEEDS = [
    {
        "repo": "sayatsirinoglu/IPTV-List",
        "path": "tr.m3u",
        "branch": "main",
        "stargazers_count": 0,
        "pushed_at": "2024-02-23T00:00:00Z",
        "updated_at": "2024-02-23T00:00:00Z",
    },
]


def api_request(url: str) -> dict:
    headers = {
        "User-Agent": "KulakTV-Source-Discovery/2.0",
        "Accept": "application/vnd.github+json",
    }
    token = str(__import__("os").environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "KulakTV-Source-Discovery/1.0",
            "Accept": "application/vnd.apple.mpegurl,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT) as response:
        return response.read(MAX_BODY + 1)


def repo_meta(full_name: str) -> dict:
    return api_request(f"https://api.github.com/repos/{full_name}")


def freshness_score(pushed_at: str) -> float:
    if not pushed_at:
        return 25
    try:
        dt = datetime.fromisoformat(pushed_at.replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    except Exception:
        return 25
    if days <= 7:
        return 100
    if days <= 30:
        return 90
    if days <= 90:
        return 75
    if days <= 180:
        return 55
    if days <= 365:
        return 35
    return 15


def static_score(channel_count: int, unique_urls: int, new_ratio: float, unique_hosts: int, pushed_at: str) -> int:
    channel_factor = min(1.0, channel_count / 80)
    diversity_factor = min(1.0, unique_hosts / max(unique_urls, 1) * 4)
    score = (
        40 * (new_ratio * 100)
        + 20 * (channel_factor * 100)
        + 20 * (diversity_factor * 100)
        + 20 * freshness_score(pushed_at)
    ) / 100
    return max(0, min(100, round(score)))


def load_previous() -> dict:
    if not STATE_PATH.exists():
        return {"version": 1, "candidates": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"version": 1, "candidates": []}
    except Exception:
        return {"version": 1, "candidates": []}


def search_repositories(query: str) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query,
        "sort": "updated",
        "order": "desc",
        "per_page": MAX_RESULTS_PER_QUERY,
    })
    data = api_request(f"https://api.github.com/search/repositories?{params}")
    items = data.get("items", [])
    return items if isinstance(items, list) else []


def repository_tree(repo_name: str, branch: str) -> dict:
    return api_request(
        "https://api.github.com/repos/"
        f"{repo_name}/git/trees/{urllib.parse.quote(branch or 'main', safe='')}?recursive=1"
    )


def candidate_paths(tree: dict) -> list[str]:
    entries = tree.get("tree", []) if isinstance(tree, dict) else []
    if not isinstance(entries, list):
        return []

    ranked: list[tuple[float, str]] = []
    for item in entries:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path = str(item.get("path") or "")
        lower = path.lower()
        if not lower.endswith((".m3u", ".m3u8", ".txt")):
            continue
        if any(part in lower for part in (
            "node_modules/", "vendor/", "tests/", "test/",
            "example/", "examples/",
        )):
            continue
        size = int(item.get("size") or 0)
        if size > MAX_BODY:
            continue

        filename = lower.rsplit("/", 1)[-1]
        rank = 50
        if filename == "tr.m3u":
            rank = 0
        elif filename in {"turkey.m3u", "turkiye.m3u", "turk.m3u"}:
            rank = 1
        elif any(hint in lower for hint in (
            "turk", "turkey", "turkiye", "iptv", "kanal", "channel",
        )):
            rank = 10
        ranked.append((rank + lower.count("/") * 0.1, path))

    ranked.sort()
    return [path for _rank, path in ranked[:MAX_PLAYLISTS_PER_REPO]]


def main() -> int:
    current_urls = set()
    if PLAYLIST_PATH.exists():
        current_urls = {
            line.strip()
            for line in PLAYLIST_PATH.read_text(encoding="utf-8").splitlines()
            if re.match(r"^https?://", line.strip(), re.I)
        }

    known_urls = {url for _name, url in SOURCES}
    known_repos = set()
    for _name, url in SOURCES:
        match = re.match(
            r"^https?://raw\.githubusercontent\.com/([^/]+/[^/]+)/.+$",
            url,
            re.I,
        )
        if match:
            known_repos.add(match.group(1).lower())

    repo_pool: dict[str, dict] = {}
    query_count = 0

    for query in SEARCH_QUERIES:
        try:
            results = search_repositories(query)
            query_count += 1
        except Exception as exc:
            print(f"::warning::Repo araması başarısız ({query}): {exc}")
            continue

        for repo in results:
            full_name = str(repo.get("full_name") or "")
            key = full_name.lower()
            if not full_name or key in known_repos or key in repo_pool:
                continue
            if repo.get("archived") or repo.get("disabled") or repo.get("fork"):
                continue
            repo_pool[key] = repo

        if len(repo_pool) >= MAX_REPOSITORIES:
            break

    ranked_repos = sorted(
        repo_pool.values(),
        key=lambda item: (
            -int(item.get("stargazers_count") or 0),
            str(item.get("updated_at") or ""),
        ),
    )[:MAX_REPOSITORIES]

    # Bootstrap a small vetted seed catalog so discovery still has something
    # to evaluate when GitHub repository search is temporarily empty.
    existing_repo_keys = {
        str(item.get("full_name") or "").lower()
        for item in ranked_repos
        if isinstance(item, dict)
    }
    for seed in DISCOVERY_SEEDS:
        key = str(seed.get("repo") or "").lower()
        if key and key not in existing_repo_keys:
            ranked_repos.append(
                {
                    "full_name": seed["repo"],
                    "default_branch": seed.get("branch", "main"),
                    "stargazers_count": seed.get("stargazers_count", 0),
                    "pushed_at": seed.get("pushed_at", ""),
                    "updated_at": seed.get("updated_at", ""),
                }
            )
            existing_repo_keys.add(key)

    results_by_url: dict[str, dict[str, object]] = {}
    for repo in ranked_repos:
        full_name = str(repo.get("full_name") or "")
        branch = str(repo.get("default_branch") or "main")
        if not full_name:
            continue

        try:
            tree = repository_tree(full_name, branch)
        except Exception as exc:
            print(f"::notice::{full_name} tree alınamadı: {exc}")
            continue

        for path in candidate_paths(tree):
            source_url = (
                f"https://raw.githubusercontent.com/{full_name}/"
                f"{urllib.parse.quote(branch, safe='')}/"
                f"{urllib.parse.quote(path, safe='/')}"
            )
            if source_url in known_urls or source_url in results_by_url:
                continue

            try:
                payload = fetch_bytes(source_url)
                playlist_text = payload.decode("utf-8-sig", errors="replace")
                channels = parse_m3u(playlist_text)
            except Exception:
                continue

            urls: list[str] = []
            hosts = set()
            for channel in channels:
                primary = str(channel.get("url") or "")
                if re.match(r"^https?://", primary, re.I):
                    urls.append(primary)
                    host = urllib.parse.urlsplit(primary).hostname or ""
                    if host:
                        hosts.add(host)
                for alt in channel.get("alternatives", []):
                    alt_url = str(alt)
                    if re.match(r"^https?://", alt_url, re.I):
                        urls.append(alt_url)
                        host = urllib.parse.urlsplit(alt_url).hostname or ""
                        if host:
                            hosts.add(host)

            # Discovery kaynağının her koşulda gerçek bir set ile değerlendirilmesini garanti et.
            hosts = set(hosts)
            unique_urls = list(dict.fromkeys(urls))
            if len(channels) < MIN_CHANNELS or len(unique_urls) < MIN_UNIQUE_URLS:
                continue

            new_urls = [url for url in unique_urls if url not in current_urls]
            new_ratio = len(new_urls) / max(1, len(unique_urls))
            if new_ratio < MIN_NEW_URL_RATIO:
                continue

            pushed_at = str(repo.get("pushed_at") or repo.get("updated_at") or "")
            score = static_score(
                len(channels),
                len(unique_urls),
                new_ratio,
                len(hosts),
                pushed_at,
            )
            if score < 55:
                continue

            results_by_url[source_url] = {
                "name": f"auto:{full_name}:{path}",
                "url": source_url,
                "repo": full_name,
                "path": path,
                "channelCount": len(channels),
                "uniqueUrls": len(unique_urls),
                "uniqueHosts": len(hosts),
                "newUrls": len(new_urls),
                "newUrlRatio": round(new_ratio, 3),
                "staticScore": score,
                "stars": int(repo.get("stargazers_count") or 0),
                "pushedAt": pushed_at,
                "status": "trial" if score >= MIN_AUTO_SCORE else "candidate",
                "urls": unique_urls[:180],
                "lastDiscoveredAt": datetime.now(timezone.utc).isoformat(),
            }

    previous = load_previous()
    old = {
        str(item.get("url")): item
        for item in previous.get("candidates", [])
        if isinstance(item, dict) and item.get("url")
    }

    merged = []
    for url, candidate in results_by_url.items():
        previous_item = old.get(url, {})
        if previous_item.get("status") == "active":
            candidate["status"] = "active"
        elif int(candidate.get("staticScore") or 0) >= MIN_AUTO_SCORE:
            candidate["status"] = "trial"

        for key in (
            "healthScore", "lastHealthAt", "healthyUrls",
            "checkedUrls", "lastError",
        ):
            if key in previous_item:
                candidate[key] = previous_item[key]
        merged.append(candidate)

    for url, previous_item in old.items():
        if url in results_by_url:
            continue
        last_seen = str(previous_item.get("lastDiscoveredAt") or "")
        try:
            days = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
            ).total_seconds() / 86400
        except Exception:
            days = 999

        # Keep active and trial entries persistent even when GitHub search no
        # longer ranks their repository. A trial source must remain in the
        # quarantine queue until health testing promotes or rejects it.
        if previous_item.get("status") in {"active", "trial"} and days <= 30:
            merged.append(previous_item)

    # Prefer active sources first, then untested trials, then previously
    # measured trials. This prevents a fresh trial from waiting indefinitely
    # behind older candidates just because its static score is lower.
    merged.sort(
        key=lambda item: (
            item.get("status") not in {"active", "trial"},
            item.get("status") == "trial" and bool(item.get("healthScore")),
            item.get("healthScore") is None,
            -int(item.get("healthScore") or 0),
            -int(item.get("staticScore") or 0),
            -int(item.get("stars") or 0),
        )
    )
    trimmed = merged[:MAX_CANDIDATES]

    STATE_PATH.write_text(
        json.dumps({
            "version": 2,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "queryCount": query_count,
            "repositoryCount": len(ranked_repos),
            "candidates": trimmed,
            "activeAutoSources": sum(
                1 for item in trimmed if item.get("status") == "active"
            ),
            "message": (
                "Aday kaynaklar günlük GitHub repo taraması ve KulakTV "
                "yayın sağlık kontrolüyle değerlendirilir."
            ),
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Kaynak keşfi: {len(trimmed)} aday / "
        f"{sum(1 for item in trimmed if item.get('status') == 'active')} aktif / "
        f"{len(ranked_repos)} repo incelendi"
    )
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
