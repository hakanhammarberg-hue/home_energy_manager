"""API endpoint(s) for core.nibe — the curve-offset heating boost and DHW
"Lyxläge varmvatten" levers.

Same reasoning as governor_api.py/ev_scheduler_api.py for being its own
small file. Most of this router keeps the same zero-I/O contract those two
files describe: never touches Home Assistant directly, only reflects
settings_store (nibe.*) and
BESSController.nibe_heating_last_decision/nibe_dhw_last_decision — whatever
the background poll (app.py's _poll_nibe, every 30s) most recently decided
and acted on. Recomputing a fresh decision here instead would mean the
dashboard could show a hypothetical outcome that was never actually applied
(see governor_api.py's docstring — same argument).

GET /api/nibe/history (Fas 5, 2026-09-24) is the deliberate exception: a
history/charting endpoint has no way to avoid reaching into Home
Assistant's own recorder, so it does — see core/nibe/history.py's
docstring for the full reasoning and why that I/O lives in its own core
module rather than here.

POST /api/nibe/dhw-luxury is the one write this router does, and mirrors
POST /api/ev-scheduler/override in spirit: a narrow, dashboard-reachable
toggle, separate from the general PATCH /api/settings mechanism the
Settings page uses for everything else. Unlike the EV override (a one-shot
per-session flag), this one just flips the persistent
nibe.dhw_luxury_enabled setting — the actual switch Håkan asked for
directly in the Nibe section of the dashboard.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

from core.nibe.history import (
    CLIMATE_ENTITY,
    CLIMATE_TARGET_KEY,
    COMPR_ENERGY_HW_ENTITY,
    COMPR_ENERGY_TOTAL_ENTITY,
    DHW_ENTITY,
    DHW_TARGET_HIGH_KEY,
    DHW_TARGET_LOW_KEY,
    HEAT_OFFSET_ENTITY,
    build_hourly_series,
    fetch_history_series,
)

router = APIRouter()


def _status_payload(bess_controller: Any) -> dict:
    """Shared response shape, so the toggle's response can update the UI
    immediately without a second round-trip to GET /api/nibe/status."""
    try:
        settings = bess_controller.settings_store.get_section("nibe")
    except Exception as e:
        logger.error(f"Error reading nibe settings: {e}")
        settings = {}

    heating = bess_controller.nibe_heating_last_decision
    dhw = bess_controller.nibe_dhw_last_decision

    return {
        "enabled": settings.get("enabled", False),
        "dhwLuxuryEnabled": settings.get("dhw_luxury_enabled", False),
        "heating": {
            "status": heating.status if heating is not None else None,
            "offsetC": heating.heat_offset_c if heating is not None else None,
            "reason": heating.reason if heating is not None else None,
        },
        "dhw": {
            "status": dhw.status if dhw is not None else None,
            "comfortMode": dhw.comfort_mode if dhw is not None else None,
            "reason": dhw.reason if dhw is not None else None,
        },
    }


@router.get("/api/nibe/status")
async def get_nibe_status() -> dict:
    """Return the Nibe module's current settings and last decisions.

    All three of ``heating``/``dhw``'s inner fields are null whenever the
    relevant switch is off (nibe.enabled for heating, nibe.dhw_luxury_enabled
    for dhw — the 30s poll no-ops entirely and clears the last decision, see
    app.py's _poll_nibe) or hasn't ticked yet since startup. That's a normal
    state, not an error — same convention as governor_api.py/
    ev_scheduler_api.py's equivalent fields.
    """
    from app import bess_controller

    return _status_payload(bess_controller)


@router.get("/api/nibe/history")
async def get_nibe_history(hours: int = 48) -> dict:
    """Hourly Nibe time series for the dashboard's history charts (Fas 5):
    curve offset, indoor temp vs. target, DHW tank temp vs. comfort band,
    and a heating/hot-water energy split derived from the two
    compressor-energy counters (enabled 2026-09-24 — see the project
    status doc's Fas 5 entry for how they were confirmed and turned on).

    `hours` is clamped to [1, 240] (240h = 10 days, HA's default recorder
    retention ceiling — asking for more just returns however much history
    actually still exists, never an error).

    Returns {"periods": []} (not an error) whenever Home Assistant's
    history endpoint can't be reached or has nothing yet — same
    None-tolerant convention as GET /api/nibe/status's heating/dhw fields.
    """
    from app import bess_controller

    hours = max(1, min(240, hours))
    end = datetime.now(UTC)
    start = end - timedelta(hours=hours)

    # Fetch and resample one extra hour of lookback BEFORE `start`, then
    # drop that lookback bucket from the result. build_hourly_series has no
    # baseline for its very first bucket (nothing was consumed yet when
    # that bucket's "value at bucket start" is snapshotted — see its own
    # docstring), so without this the first requested hour's energy delta
    # would always be None even when a real baseline exists a moment
    # earlier. Padding the resampling range by one hour turns that
    # always-None bucket into the throwaway lookback bucket instead.
    controller = bess_controller.nibe_controller
    series = fetch_history_series(controller.base_url, controller.headers, hours + 1)
    if not series:
        return {"periods": []}

    rows = build_hourly_series(series, start - timedelta(hours=1), end)[1:]

    periods = []
    for row in rows:
        total_kwh = row.get(f"{COMPR_ENERGY_TOTAL_ENTITY}__delta")
        hw_kwh = row.get(f"{COMPR_ENERGY_HW_ENTITY}__delta")
        space_heating_kwh = (
            max(0.0, total_kwh - hw_kwh)
            if total_kwh is not None and hw_kwh is not None
            else None
        )
        periods.append(
            {
                "timestamp": row["timestamp"],
                "offsetC": row.get(HEAT_OFFSET_ENTITY),
                "indoorActualC": row.get(CLIMATE_ENTITY),
                "indoorTargetC": row.get(CLIMATE_TARGET_KEY),
                "dhwActualC": row.get(DHW_ENTITY),
                "dhwTargetHighC": row.get(DHW_TARGET_HIGH_KEY),
                "dhwTargetLowC": row.get(DHW_TARGET_LOW_KEY),
                "totalEnergyKwh": total_kwh,
                "hwEnergyKwh": hw_kwh,
                "spaceHeatingEnergyKwh": space_heating_kwh,
            }
        )

    return {"periods": periods}


@router.post("/api/nibe/dhw-luxury")
async def set_dhw_luxury_enabled(body: dict) -> dict:
    """Flip the Lyxläge varmvatten dashboard switch.

    Body: {"enabled": true|false} — matches patch_settings' own plain-dict
    convention (backend/api.py) rather than introducing a pydantic model
    for a single boolean field.

    This only ever changes nibe.dhw_luxury_enabled in settings_store — the
    next poll tick (_poll_nibe) picks it up and either starts steering DHW
    comfort mode (enabled=True) or leaves the register alone from then on
    (enabled=False; it does NOT force a write back to Normal on disable —
    see app.py's _poll_nibe docstring for why that's a deliberate choice,
    same as the pump's own menu remaining the source of truth whenever this
    lever isn't actively steering it).
    """
    from app import bess_controller

    if "enabled" not in body or not isinstance(body["enabled"], bool):
        raise HTTPException(
            status_code=422, detail="Body must be {'enabled': true|false}"
        )

    settings = bess_controller.settings_store.get_section("nibe")
    settings["dhw_luxury_enabled"] = body["enabled"]
    bess_controller.settings_store.save_section("nibe", settings)

    return _status_payload(bess_controller)
