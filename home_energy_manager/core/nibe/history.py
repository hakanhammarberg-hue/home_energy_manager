"""core.nibe.history — hourly time series for the Nibe F750 dashboard
charts (Fas 5, 2026-09-24): curve offset, indoor temperature vs. target,
DHW tank temperature vs. comfort band, and heating/hot-water energy.

No InfluxDB dependency needed here, unlike core/bess's battery/consumption
history — the entities involved (climate.f750_climate_system_s1,
water_heater.f750_hot_water, and the two compr_energy_* counters once
enabled) are already recorded richly by Home Assistant's own default
recorder (~10 day retention), confirmed live 2026-09-24 (245-598 data
points per entity per 24h). This module reads that history directly via
HA's REST API instead of standing up a second storage path.

Two layers, deliberately split so the resampling logic is unit-testable
without any HTTP/HA dependency (see core/nibe/tests/test_history.py):
  - fetch_history_series() — I/O: calls HA's /api/history/period endpoint
    and extracts a flat, sorted (timestamp, value) list per entity/
    attribute of interest.
  - build_hourly_series() — pure: takes those flat lists and produces one
    row per hour bucket between start/end, carrying the last known value
    forward (never guessing backward past the first real reading).

This intentionally breaks backend/nibe_api.py's usual "zero I/O" rule
(see that file's own module docstring, which explains why its other
endpoints only ever reflect settings_store/last-decision state) — a
history endpoint has no way to avoid reaching into Home Assistant. Kept
in its own core module (like core/nibe/controller.py, which also talks to
HA directly) rather than folded into NibeController, because it reads a
much wider set of entities for a different purpose: charting, not
control, and never writes anything.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests

logger = logging.getLogger(__name__)

# Confirmed live 2026-09-24 (see the project status doc's Fas 5 entry) —
# real entity IDs checked directly against Håkan's Home Assistant, not
# guessed placeholders. compr_energy_* were disabled_by "integration"
# until that day; enabled + config-entry-reloaded as part of this work.
HEAT_OFFSET_ENTITY = "number.heat_offset_s1_47011"
CLIMATE_ENTITY = "climate.f750_climate_system_s1"
DHW_ENTITY = "water_heater.f750_hot_water"
COMPR_ENERGY_TOTAL_ENTITY = "sensor.compr_energy_total_43144"
COMPR_ENERGY_HW_ENTITY = "sensor.compr_energy_hw_43305"

ALL_ENTITIES = [
    HEAT_OFFSET_ENTITY,
    CLIMATE_ENTITY,
    DHW_ENTITY,
    COMPR_ENERGY_TOTAL_ENTITY,
    COMPR_ENERGY_HW_ENTITY,
]

# Climate/DHW carry a target value alongside the actual reading, both as
# attributes on the SAME entity. Parsed out as their own synthetic series
# keys below so build_hourly_series() can stay generic — one flat series
# in, one output column out, no special-casing of "this key has a sibling".
CLIMATE_TARGET_KEY = "climate_target"
DHW_TARGET_HIGH_KEY = "dhw_target_high"
DHW_TARGET_LOW_KEY = "dhw_target_low"

_EXTRA_ATTRIBUTE_SERIES: dict[str, tuple[str, str]] = {
    CLIMATE_TARGET_KEY: (CLIMATE_ENTITY, "temperature"),
    DHW_TARGET_HIGH_KEY: (DHW_ENTITY, "target_temp_high"),
    DHW_TARGET_LOW_KEY: (DHW_ENTITY, "target_temp_low"),
}

_ATTRIBUTE_BY_ENTITY: dict[str, str | None] = {
    HEAT_OFFSET_ENTITY: None,  # plain number state, not an attribute
    CLIMATE_ENTITY: "current_temperature",
    DHW_ENTITY: "current_temperature",
    COMPR_ENERGY_TOTAL_ENTITY: None,
    COMPR_ENERGY_HW_ENTITY: None,
}


@dataclass(frozen=True)
class HistoryPoint:
    """One (timestamp, value) reading. `value` is None for a state HA
    recorded as unavailable/unknown/non-numeric — callers skip it rather
    than treating it as zero."""

    at: datetime
    value: float | None


def _safe_float(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _extract_series(
    raw_states: list[dict], attribute: str | None
) -> list[HistoryPoint]:
    """Turn one entity's raw HA history states into a sorted (time, value)
    list. `attribute=None` reads the bare `state` string (e.g. the
    heat-offset number entity); otherwise reads that key out of
    `attributes` (e.g. climate's `current_temperature`)."""
    points = []
    for entry in raw_states:
        ts_raw = entry.get("last_updated") or entry.get("last_changed")
        if not ts_raw:
            continue
        try:
            at = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except ValueError:
            continue

        if attribute is None:
            value = _safe_float(entry.get("state"))
        else:
            value = _safe_float((entry.get("attributes") or {}).get(attribute))

        points.append(HistoryPoint(at=at, value=value))

    points.sort(key=lambda p: p.at)
    return points


def fetch_history_series(
    base_url: str,
    headers: dict,
    hours: int,
    entity_ids: list[str] | None = None,
) -> dict[str, list[HistoryPoint]]:
    """I/O: fetch raw history for `entity_ids` (default ALL_ENTITIES) over
    the last `hours` from Home Assistant's recorder, and extract each
    entity's (and each attribute-derived synthetic key's) (time, value)
    series. Returns {} on any request failure or invalid response — callers
    treat that the same as "no data yet", the same None-on-failure
    convention NibeController itself uses for a single-value read.
    """
    entity_ids = entity_ids or ALL_ENTITIES
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)

    url = f"{base_url}/api/history/period/{start.isoformat()}"
    params = {
        "filter_entity_id": ",".join(entity_ids),
        "end_time": end.isoformat(),
        "minimal_response": "false",
        # False, not the HA default True: climate/water_heater's useful
        # values live in attributes (current_temperature etc.), and an
        # attribute-only update is exactly what "significant changes only"
        # is liable to drop — confirmed empirically that leaving this at
        # the default still returns rich data, but False is the safer,
        # explicit choice for what this endpoint actually needs.
        "significant_changes_only": "false",
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Could not fetch Nibe history from Home Assistant: %s", e)
        return {}

    try:
        raw = response.json()
    except ValueError:
        logger.warning("Nibe history response was not valid JSON")
        return {}

    # HA's /api/history/period returns one list per entity that actually
    # has history in the window — entities with zero history are simply
    # omitted (not an empty placeholder list), so pairing must go by the
    # entity_id each sub-list itself carries, not by position.
    series_by_entity: dict[str, list[dict]] = {}
    for entity_states in raw:
        if not entity_states:
            continue
        entity_id = entity_states[0].get("entity_id")
        if entity_id:
            series_by_entity[entity_id] = entity_states

    result: dict[str, list[HistoryPoint]] = {}
    for entity_id in entity_ids:
        raw_states = series_by_entity.get(entity_id, [])
        result[entity_id] = _extract_series(
            raw_states, _ATTRIBUTE_BY_ENTITY.get(entity_id)
        )

    for key, (entity_id, attribute) in _EXTRA_ATTRIBUTE_SERIES.items():
        if entity_id not in entity_ids:
            continue
        raw_states = series_by_entity.get(entity_id, [])
        result[key] = _extract_series(raw_states, attribute)

    return result


def build_hourly_series(
    series_by_key: dict[str, list[HistoryPoint]],
    start: datetime,
    end: datetime,
) -> list[dict]:
    """Pure: resample each key's (time, value) list onto hourly buckets
    covering [start, end) (both timezone-aware), carrying the last known
    value forward into buckets with no new reading of their own. A bucket
    before a key's first data point is left as None for that key — no
    guessing backward past the first real reading.

    Returns one row per hour: {"timestamp": <bucket end, ISO 8601>,
    <key>: value, ...} for every key in series_by_key, plus
    "<key>__delta" for each of the two compr-energy keys present — the
    per-hour increase of that cumulative counter, floored at 0 so a
    counter reset/rollover between readings never shows as a bogus
    negative bar.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")

    bucket_count = max(0, int((end - start).total_seconds() // 3600))
    bucket_starts = [start + timedelta(hours=i) for i in range(bucket_count)]

    energy_keys = [
        k
        for k in (COMPR_ENERGY_TOTAL_ENTITY, COMPR_ENERGY_HW_ENTITY)
        if k in series_by_key
    ]

    last_value: dict[str, float | None] = dict.fromkeys(series_by_key, None)
    cursor: dict[str, int] = dict.fromkeys(series_by_key, 0)

    rows = []
    for bucket_start in bucket_starts:
        bucket_end = bucket_start + timedelta(hours=1)

        # Snapshot each energy counter's value AS OF the start of this
        # bucket (i.e. wherever last_value already sits, before this
        # bucket's own points are folded in) so the delta below is exactly
        # this bucket's consumption, not a running total.
        counter_at_bucket_start = {key: last_value[key] for key in energy_keys}

        for key, points in series_by_key.items():
            idx = cursor[key]
            while idx < len(points) and points[idx].at <= bucket_end:
                if points[idx].value is not None:
                    last_value[key] = points[idx].value
                idx += 1
            cursor[key] = idx

        row: dict = {"timestamp": bucket_end.isoformat()}
        for key in series_by_key:
            row[key] = last_value[key]

        for key in energy_keys:
            before = counter_at_bucket_start[key]
            after = last_value[key]
            row[f"{key}__delta"] = (
                max(0.0, after - before) if before is not None and after is not None else None
            )

        rows.append(row)

    return rows
