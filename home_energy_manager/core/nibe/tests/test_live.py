"""Unit tests for core.nibe.live.fetch_live_snapshot.

fetch_live_snapshot uses a requests.Session internally (see its own
docstring for why: one GET per entity, reusing a connection, rather than
pulling the whole /api/states state machine) — these tests mock
requests.Session so they never touch a network.
"""

from unittest.mock import Mock, patch

from core.nibe.history import CLIMATE_ENTITY, DHW_ENTITY, HEAT_OFFSET_ENTITY
from core.nibe.live import (
    CHARGE_PUMP_SPEED_ENTITY,
    COMPR_POWER_ENTITY,
    COMPR_STATE_ENTITY,
    DEGREE_MINUTES_ENTITY,
    PRIO_ENTITY,
    fetch_live_snapshot,
)

BASE_URL = "http://homeassistant.local:8123"
HEADERS = {"Authorization": "Bearer test-token"}


def _state(entity_id: str, state: str, attributes: dict | None = None) -> dict:
    return {"entity_id": entity_id, "state": state, "attributes": attributes or {}}


def _mock_session(states_by_entity: dict[str, dict | None]):
    """A Mock standing in for requests.Session(): .get(url, ...) inspects
    the URL to find which entity was requested and returns a Mock response
    whose .json() gives back that entity's canned state dict (or a 404-like
    unavailable state if the entity was omitted, mirroring how a genuinely
    disabled/unavailable entity would look after .raise_for_status())."""

    def fake_get(url, headers=None, timeout=None):
        entity_id = url.rsplit("/", 1)[-1]
        response = Mock()
        response.raise_for_status = Mock()
        response.json = Mock(
            return_value=states_by_entity.get(
                entity_id, {"entity_id": entity_id, "state": "unavailable"}
            )
        )
        return response

    session = Mock()
    session.get = Mock(side_effect=fake_get)
    session.close = Mock()
    return session


def test_full_snapshot_maps_every_field():
    states = {
        PRIO_ENTITY: _state(PRIO_ENTITY, "Heat"),
        COMPR_POWER_ENTITY: _state(COMPR_POWER_ENTITY, "1.8"),
        COMPR_STATE_ENTITY: _state(COMPR_STATE_ENTITY, "RUNNING"),
        CHARGE_PUMP_SPEED_ENTITY: _state(CHARGE_PUMP_SPEED_ENTITY, "45"),
        DEGREE_MINUTES_ENTITY: _state(DEGREE_MINUTES_ENTITY, "-120.5"),
        HEAT_OFFSET_ENTITY: _state(HEAT_OFFSET_ENTITY, "1"),
        CLIMATE_ENTITY: _state(
            CLIMATE_ENTITY,
            "heat",
            {"current_temperature": 21.8, "temperature": 21.5},
        ),
        DHW_ENTITY: _state(
            DHW_ENTITY,
            "eco",
            {"current_temperature": 49.5, "target_temp_high": 52, "target_temp_low": 48},
        ),
    }

    with patch("core.nibe.live.requests.Session", return_value=_mock_session(states)):
        snapshot = fetch_live_snapshot(BASE_URL, HEADERS)

    assert snapshot["prio"] == "Heat"
    assert snapshot["compressorPowerKw"] == 1.8
    assert snapshot["compressorState"] == "RUNNING"  # text state, not coerced to float
    assert snapshot["chargePumpSpeedPct"] == 45.0
    assert snapshot["degreeMinutes"] == -120.5
    assert snapshot["heatOffsetC"] == 1.0
    assert snapshot["indoorActualC"] == 21.8
    assert snapshot["indoorTargetC"] == 21.5
    assert snapshot["dhwActualC"] == 49.5
    assert snapshot["dhwTargetHighC"] == 52.0
    assert snapshot["dhwTargetLowC"] == 48.0


def test_unavailable_entity_reads_as_none_not_zero():
    """A disabled/unavailable register must show up as None (the frontend's
    cue to render "—"), never as a fabricated 0.0 that would look like a
    real, if boring, reading."""
    states = {
        PRIO_ENTITY: _state(PRIO_ENTITY, "OFF"),
        # COMPR_POWER_ENTITY deliberately omitted -> "unavailable" from the mock
    }

    with patch("core.nibe.live.requests.Session", return_value=_mock_session(states)):
        snapshot = fetch_live_snapshot(BASE_URL, HEADERS)

    assert snapshot["prio"] == "OFF"
    assert snapshot["compressorPowerKw"] is None


def test_everything_unavailable_returns_empty_dict():
    with patch("core.nibe.live.requests.Session", return_value=_mock_session({})):
        snapshot = fetch_live_snapshot(BASE_URL, HEADERS)

    assert snapshot == {}


def test_partial_failure_still_returns_what_succeeded():
    """Home Assistant answering for some entities but not others (a couple
    of registers genuinely down) should not hide the entities that did
    come back — only a total failure collapses to {}."""
    states = {
        PRIO_ENTITY: _state(PRIO_ENTITY, "Hot Water"),
        DEGREE_MINUTES_ENTITY: _state(DEGREE_MINUTES_ENTITY, "50"),
    }

    with patch("core.nibe.live.requests.Session", return_value=_mock_session(states)):
        snapshot = fetch_live_snapshot(BASE_URL, HEADERS)

    assert snapshot["prio"] == "Hot Water"
    assert snapshot["degreeMinutes"] == 50.0
    assert snapshot["compressorPowerKw"] is None
    assert snapshot["indoorActualC"] is None
