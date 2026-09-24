"""Unit tests for core.nibe.history.

build_hourly_series() is pure (no HA, no mocking) — covered directly.
fetch_history_series() is the I/O layer — covered with a mocked
`requests.get` so these tests never touch a network.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

from core.nibe.history import (
    CLIMATE_ENTITY,
    COMPR_ENERGY_HW_ENTITY,
    COMPR_ENERGY_TOTAL_ENTITY,
    HEAT_OFFSET_ENTITY,
    HistoryPoint,
    build_hourly_series,
    fetch_history_series,
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 24, hour, minute, tzinfo=UTC)


# ---------------------------------------------------------------------------
# build_hourly_series
# ---------------------------------------------------------------------------


def test_carries_last_value_forward_across_buckets():
    series = {
        HEAT_OFFSET_ENTITY: [
            HistoryPoint(at=_at(0, 5), value=0.0),
            HistoryPoint(at=_at(0, 30), value=2.0),
            # nothing in hour 1 — should carry the 2.0 forward
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(2))

    assert len(rows) == 2
    assert rows[0][HEAT_OFFSET_ENTITY] == 2.0  # last reading at/before 01:00
    assert rows[1][HEAT_OFFSET_ENTITY] == 2.0  # carried forward, no new data


def test_bucket_before_first_reading_is_none():
    series = {
        HEAT_OFFSET_ENTITY: [
            HistoryPoint(at=_at(1, 30), value=2.0),
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(2))

    assert rows[0][HEAT_OFFSET_ENTITY] is None  # nothing yet by 01:00
    assert rows[1][HEAT_OFFSET_ENTITY] == 2.0


def test_none_valued_points_are_skipped_not_treated_as_zero():
    series = {
        HEAT_OFFSET_ENTITY: [
            HistoryPoint(at=_at(0, 5), value=1.5),
            HistoryPoint(at=_at(0, 45), value=None),  # e.g. "unavailable"
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(1))

    assert rows[0][HEAT_OFFSET_ENTITY] == 1.5  # the None reading didn't clobber it


def test_energy_delta_is_per_bucket_not_cumulative():
    # Deliberately off exact hour boundaries (like real Nibe readings) so a
    # point isn't ambiguous about which bucket's "last value at/before
    # bucket end" it belongs to.
    series = {
        COMPR_ENERGY_TOTAL_ENTITY: [
            HistoryPoint(at=_at(0, 5), value=100.0),
            HistoryPoint(at=_at(1, 5), value=101.5),
            HistoryPoint(at=_at(2, 5), value=104.0),
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(3))

    # Bucket 0 has no baseline reading from BEFORE it starts (the 100.0
    # reading lands inside bucket 0 itself, not before it), so its delta is
    # unknowable — None, not 0.
    assert rows[0][f"{COMPR_ENERGY_TOTAL_ENTITY}__delta"] is None
    assert rows[1][f"{COMPR_ENERGY_TOTAL_ENTITY}__delta"] == 1.5  # 100 -> 101.5
    assert rows[2][f"{COMPR_ENERGY_TOTAL_ENTITY}__delta"] == 2.5  # 101.5 -> 104.0


def test_energy_counter_reset_clamps_delta_to_zero_not_negative():
    series = {
        COMPR_ENERGY_TOTAL_ENTITY: [
            HistoryPoint(at=_at(0, 0), value=500.0),
            HistoryPoint(at=_at(1, 0), value=0.2),  # counter reset/rollover
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(2))

    assert rows[1][f"{COMPR_ENERGY_TOTAL_ENTITY}__delta"] == 0.0


def test_delta_is_none_without_a_baseline_reading():
    series = {
        COMPR_ENERGY_HW_ENTITY: [
            HistoryPoint(at=_at(0, 30), value=10.0),
        ]
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(1))

    # No known counter value AT bucket start (00:00), so the delta for this
    # first bucket is unknowable, not "10.0 consumed from nothing".
    assert rows[0][f"{COMPR_ENERGY_HW_ENTITY}__delta"] is None


def test_naive_datetimes_are_rejected():
    import pytest

    with pytest.raises(ValueError):
        build_hourly_series({}, start=datetime(2026, 9, 24), end=datetime(2026, 9, 25))


def test_multiple_keys_resampled_independently():
    series = {
        HEAT_OFFSET_ENTITY: [HistoryPoint(at=_at(0, 10), value=2.0)],
        CLIMATE_ENTITY: [HistoryPoint(at=_at(0, 20), value=21.5)],
    }
    rows = build_hourly_series(series, start=_at(0), end=_at(1))

    assert rows[0][HEAT_OFFSET_ENTITY] == 2.0
    assert rows[0][CLIMATE_ENTITY] == 21.5


# ---------------------------------------------------------------------------
# fetch_history_series (I/O layer, mocked)
# ---------------------------------------------------------------------------


def _ha_history_response(entity_id: str, attribute: str | None, value) -> list[dict]:
    entry = {
        "entity_id": entity_id,
        "state": str(value) if attribute is None else "on",
        "last_updated": "2026-09-24T12:00:00+00:00",
        "attributes": {attribute: value} if attribute else {},
    }
    return [entry]


@patch("core.nibe.history.requests.get")
def test_fetch_history_series_parses_matched_entities(mock_get):
    mock_response = Mock()
    mock_response.json.return_value = [
        _ha_history_response(HEAT_OFFSET_ENTITY, None, 1.0),
        _ha_history_response(CLIMATE_ENTITY, "current_temperature", 22.0),
    ]
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    series = fetch_history_series(
        "http://supervisor/core",
        {"Authorization": "Bearer x"},
        hours=24,
        entity_ids=[HEAT_OFFSET_ENTITY, CLIMATE_ENTITY],
    )

    assert series[HEAT_OFFSET_ENTITY][0].value == 1.0
    assert series[CLIMATE_ENTITY][0].value == 22.0


@patch("core.nibe.history.requests.get")
def test_fetch_history_series_returns_empty_dict_on_request_failure(mock_get):
    import requests

    mock_get.side_effect = requests.ConnectionError("boom")

    series = fetch_history_series(
        "http://supervisor/core", {"Authorization": "Bearer x"}, hours=24
    )

    assert series == {}


@patch("core.nibe.history.requests.get")
def test_fetch_history_series_handles_entities_missing_from_response(mock_get):
    # HA omits entities with zero history entirely — must not KeyError.
    mock_response = Mock()
    mock_response.json.return_value = [
        _ha_history_response(HEAT_OFFSET_ENTITY, None, 1.0),
    ]
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    series = fetch_history_series(
        "http://supervisor/core",
        {"Authorization": "Bearer x"},
        hours=24,
        entity_ids=[HEAT_OFFSET_ENTITY, CLIMATE_ENTITY],
    )

    assert series[CLIMATE_ENTITY] == []
