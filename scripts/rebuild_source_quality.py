#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from update_channels import (
    apply_player_quality,
    load_player_telemetry,
    load_source_quality,
    save_source_quality,
)


def main() -> int:
    source_quality_doc = load_source_quality()
    quality = source_quality_doc.get("sources", source_quality_doc)
    if not isinstance(quality, dict):
        quality = {}

    telemetry = load_player_telemetry()
    updated = apply_player_quality(
        quality,
        telemetry,
        datetime.now(timezone.utc).isoformat(),
    )
    save_source_quality(
        updated,
        datetime.now(timezone.utc).isoformat(),
    )
    print(f"Ortak kaynak kalitesi oyuncu verisiyle yenilendi: {len(updated)} kaynak")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
