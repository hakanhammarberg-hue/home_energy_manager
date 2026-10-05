"""core.nibe.live — a single real-time snapshot of the Nibe F750's current
operating state, for the dashboard's "Nibe drift" page (2026-09-28, built
at Håkan's request: "jag efterlyser driftdata, vad som sker för sekunden").

This sits alongside core.nibe.history (multi-hour charts) and
core.nibe.controller (the two write-gated control levers) but answers a
different question: not "what happened over the last N hours" and not
"read/write the two levers this app controls", but "what is the pump
actually doing right now" — compressor power/frequency/current, Prio
(Off/Hot Water/Heat/Pool), degree minutes, charge/supply pump speed, and
electric-addition power, alongside the same indoor/DHW temperatures and
applied curve offset the history charts already show. Read-only, zero
writes, same "None means no data right now" convention as controller.py
and history.py.

Entities confirmed live against Håkan's Home Assistant 2026-09-28 (most
needed `enabled: true` + a config-entry reload first — see the project
status doc's "Nibe drift" entry for the exact sequence; several of the
~650 disabled-by-default F750 registers, same story as history.py's own
compr_energy_* counters).

WHY INDIVIDUAL /api/states/<id> CALLS, NOT ONE /api/states DUMP
    Home Assistant's REST API has no "give me just these N entities"
    filter on the bulk /api/states endpoint (unlike /api/history/period,
    which does take filter_entity_id — see history.py). Pulling the whole
    state machine just to read a dozen values would mean transferring and
    parsing every entity this HA instance has, dwarfing what an 8-12s
    dashboard poll should cost. One GET per entity, reusing a single
    requests.Session for connection keep-alive, stays proportional to
    what's actually needed and is cheap on a LAN round-trip to Home
    Assistant either way.
"""

from __future__ import annotations

import logging

import requests

from core.nibe.history import CLIMATE_ENTITY, DHW_ENTITY, HEAT_OFFSET_ENTITY

logger = logging.getLogger(__name__)

PRIO_ENTITY = "sensor.prio_43086"
COMPR_POWER_ENTITY = "sensor.compr_in_power_43141"
COMPR_POWER_MEAN_ENTITY = "sensor.compr_in_power_mean_43375"
COMPR_CURRENT_ENTITY = "sensor.compr_in_current_43147"
COMPR_FREQUENCY_ACTUAL_ENTITY = "sensor.compressor_frequency_actual_43136"
COMPR_STATE_ENTITY = "sensor.compressor_state_ep14_43427"
CHARGE_PUMP_SPEED_ENTITY = "sensor.chargepump_speed_43181"
SUPPLY_PUMP_SPEED_ENTITY = "sensor.supply_pump_speed_ep14_43437"
EL_ADD_POWER_ENTITY = "sensor.int_el_add_power_43084"
DEGREE_MINUTES_ENTITY = "number.degree_minutes_16_bit_43005"

# Added 2026-10-05 — the pump's own "effektvakt" (power-guard) settings,
# for the dashboard's "what is effektvakt actually set to right now" ask.
# See backend/app.py's NIBE_EFFEKTVAKT_MAX_POWER_ENTITY comment and
# core/nibe/controller.py's EFFEKTVAKT tier for the full story. Confirmed
# live 2026-10-05: both read as None here (register "unavailable") because
# effektvakt has never been turned on at the pump's own panel — that is
# the honest current setting, not a bug in this module.
EFFEKTVAKT_MAX_POWER_ENTITY = "number.max_int_add_power_47212"
EFFEKTVAKT_FUSE_ENTITY = "number.fuse_47214"

# Plain state (no attribute) reads. Climate/DHW are handled separately
# below since the values this page wants live in their *attributes*, not
# the bare `state` string (same split history.py makes).
_PLAIN_STATE_ENTITIES = [
    PRIO_ENTITY,
    COMPR_POWER_ENTITY,
    COMPR_POWER_MEAN_ENTITY,
    COMPR_CURRENT_ENTITY,
    COMPR_FREQUENCY_ACTUAL_ENTITY,
    COMPR_STATE_ENTITY,
    CHARGE_PUMP_SPEED_ENTITY,
    SUPPLY_PUMP_SPEED_ENTITY,
    EL_ADD_POWER_ENTITY,
    DEGREE_MINUTES_ENTITY,
    HEAT_OFFSET_ENTITY,
    EFFEKTVAKT_MAX_POWER_ENTITY,
    EFFEKTVAKT_FUSE_ENTITY,
]

# Numeric among the above — everything except Prio and Compressor State,
# which are short text/enum values ("OFF"/"Hot Water"/..., "STOPPED"/...).
_NUMERIC_ENTITIES = {
    COMPR_POWER_ENTITY,
    COMPR_POWER_MEAN_ENTITY,
    COMPR_CURRENT_ENTITY,
    COMPR_FREQUENCY_ACTUAL_ENTITY,
    CHARGE_PUMP_SPEED_ENTITY,
    SUPPLY_PUMP_SPEED_ENTITY,
    EL_ADD_POWER_ENTITY,
    DEGREE_MINUTES_ENTITY,
    HEAT_OFFSET_ENTITY,
    EFFEKTVAKT_MAX_POWER_ENTITY,
    EFFEKTVAKT_FUSE_ENTITY,
}


def _safe_float(raw: object) -> float | None:
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _get_state(
    session: requests.Session, base_url: str, headers: dict, entity_id: str
) -> dict | None:
    """One entity's raw HA state dict, or None on any failure/unavailable
    state. Mirrors NibeController._get_raw_state's request shape, but
    returns the full dict (state + attributes) since some callers need
    attributes, not just the bare state string."""
    url = f"{base_url}/api/states/{entity_id}"
    try:
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Could not reach Home Assistant for %s: %s", entity_id, e)
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    if data.get("state") in ("unavailable", "unknown", None):
        return None
    return data


def fetch_live_snapshot(base_url: str, headers: dict) -> dict:
    """Fetch every entity this page needs and return a flat, camelCase-keyed
    dict ready for the API response. A field is None whenever its entity is
    unavailable/unreachable — never a fabricated zero — so the frontend can
    show "—" rather than a misleading 0.0. Returns {} only if EVERY read
    fails (e.g. Home Assistant itself is unreachable); a partial read still
    returns whatever did succeed, since these entities are independent
    registers and one being down shouldn't hide the rest.
    """
    session = requests.Session()
    try:
        plain: dict[str, dict | None] = {
            entity_id: _get_state(session, base_url, headers, entity_id)
            for entity_id in _PLAIN_STATE_ENTITIES
        }
        climate = _get_state(session, base_url, headers, CLIMATE_ENTITY)
        dhw = _get_state(session, base_url, headers, DHW_ENTITY)
    finally:
        session.close()

    if not any(plain.values()) and climate is None and dhw is None:
        return {}

    def state_of(entity_id: str) -> str | float | None:
        data = plain.get(entity_id)
        if data is None:
            return None
        raw = data.get("state")
        return _safe_float(raw) if entity_id in _NUMERIC_ENTITIES else raw

    def attr_of(data: dict | None, attribute: str) -> float | None:
        if data is None:
            return None
        return _safe_float((data.get("attributes") or {}).get(attribute))

    return {
        "prio": state_of(PRIO_ENTITY),
        "compressorPowerKw": state_of(COMPR_POWER_ENTITY),
        "compressorPowerMeanKw": state_of(COMPR_POWER_MEAN_ENTITY),
        "compressorCurrentA": state_of(COMPR_CURRENT_ENTITY),
        "compressorFrequencyHz": state_of(COMPR_FREQUENCY_ACTUAL_ENTITY),
        "compressorState": state_of(COMPR_STATE_ENTITY),
        "chargePumpSpeedPct": state_of(CHARGE_PUMP_SPEED_ENTITY),
        "supplyPumpSpeedPct": state_of(SUPPLY_PUMP_SPEED_ENTITY),
        "electricAdditionKw": state_of(EL_ADD_POWER_ENTITY),
        "degreeMinutes": state_of(DEGREE_MINUTES_ENTITY),
        "heatOffsetC": state_of(HEAT_OFFSET_ENTITY),
        "effektvaktMaxPowerKw": state_of(EFFEKTVAKT_MAX_POWER_ENTITY),
        "effektvaktFuseRatingA": state_of(EFFEKTVAKT_FUSE_ENTITY),
        "indoorActualC": attr_of(climate, "current_temperature"),
        "indoorTargetC": attr_of(climate, "temperature"),
        "dhwActualC": attr_of(dhw, "current_temperature"),
        "dhwTargetHighC": attr_of(dhw, "target_temp_high"),
        "dhwTargetLowC": attr_of(dhw, "target_temp_low"),
    }
