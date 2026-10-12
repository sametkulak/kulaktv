#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone

from update_channels import (
    apply_player_quality,
    load_player_telemetry,
    load_source_quality,
    save_source_quality,
    source_quality_score,
)


def main() -> int:
    source_quality_doc = load_source_quality()
    quality = source_quality_doc.get("sources", source_quality_doc)
    if not isinstance(quality, dict):
        quality = {}

    telemetry = load_player_telemetry()

    # Recompute the pure server score first so previously blended player
    # telemetry cannot linger when the telemetry store is reset/cleaned.
    for record in quality.values():
        if not isinstance(record, dict):
            continue
        record["score"] = source_quality_score(record)
        for key in (
            "healthScore", "playerScore", "playerEvents",
            "playerSuccesses", "playerFailures", "playerStalls",
            "playerWeight", "lastPlayerEventAt"
        ):
            record.pop(key, None)

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
