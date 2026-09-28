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

GET /api/nibe/history (Fas 5, 2026-09-24) and GET /api/nibe/live
(2026-09-28) are the deliberate exceptions: a history/charting endpoint
and a real-time snapshot endpoint both have no way to avoid reaching into
Home Assistant directly, so they do — see core/nibe/history.py's and
core/nibe/live.py's own docstrings for the full reasoning and why that I/O
lives in its own core module rather than here.

GET /api/nibe/savings (2026-09-28, dashboard compaction phase) is a third
such exception, for the same reason as /history: estimating today's
price-peak-reduction savings needs today's actually-applied heat_offset_s1
history from Home Assistant, so it reaches in directly. The calculation
itself is pure (core/nibe/savings.py) — this endpoint's only job is to
assemble that module's inputs from history.py's HA read plus
price_manager's already-cached today's prices, see that endpoint's own
docstring below for the full reasoning.

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

from core.bess import time_utils
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
from core.nibe.live import fetch_live_snapshot
from core.nibe.savings import estimate_reduction_savings

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


@router.get("/api/nibe/live")
async def get_nibe_live() -> dict:
    """Real-time snapshot for the "Nibe drift" page (2026-09-28): the same
    settings/last-decision payload GET /api/nibe/status returns, plus a
    fresh, uncached `live` read of the pump's current compressor power/
    frequency/current, Prio, degree minutes, pump speeds, electric-addition
    power and applied curve offset/temperatures straight from Home
    Assistant — see core/nibe/live.py's docstring for why this is, like
    GET /api/nibe/history, a deliberate exception to this router's usual
    zero-I/O rule.

    `live` is `{}` whenever Home Assistant can't be reached at all (a
    partial read still returns whatever succeeded) — same empty-on-failure
    convention as GET /api/nibe/history's `periods`.
    """
    from app import bess_controller

    payload = _status_payload(bess_controller)
    controller = bess_controller.nibe_controller
    payload["live"] = fetch_live_snapshot(controller.base_url, controller.headers)
    return payload


@router.get("/api/nibe/savings")
async def get_nibe_savings() -> dict:
    """Today-so-far estimated savings from the price-peak reduction lever
    (core/nibe/decision.py's FIFTH LEVER, "reduced_expensive_price") — see
    core/nibe/savings.py's module docstring for the full methodology and
    why it's scoped to today only and to this one lever.

    Assembles two independent things onto the same hourly grid:
      1. The actually-applied number.heat_offset_s1 register value for each
         hour since local midnight, via history.py's existing HA-recorder
         read (same source /api/nibe/history already uses).
      2. That hour's spot price, averaged from today's already-cached
         quarter-hourly buy-price array (core.bess.price_manager) — the
         same array _poll_nibe reads every cycle, so this costs no extra
         Nordpool/price-source call.

    Scoped to TODAY ONLY (not a rolling 24h/48h window like /history):
    price_manager only ever holds the CURRENT day's full price array —
    there is no retained "yesterday's prices" to align against a rolling
    window that crosses midnight, so extending this past today would mean
    silently pairing some hours with the wrong day's price. Today-so-far is
    the honest boundary of what's actually computable right now (see the
    design doc's Del 2 for the 2-day-window future-work note).

    Returns a zeroed estimate (not an error) whenever Home Assistant's
    history endpoint or the price source has nothing yet — same
    None/empty-tolerant convention as /api/nibe/history and
    /api/nibe/status.
    """
    from app import bess_controller

    controller = bess_controller.nibe_controller
    tz = time_utils.TIMEZONE
    now_local = datetime.now(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_elapsed = max(1, int((now_local - midnight_local).total_seconds() // 3600) + 1)

    empty_response = {
        "hours": [],
        "totalAvoidedKwh": 0.0,
        "totalSavingsKr": 0.0,
        "activeHours": 0,
        "heatLossCoefficientKwPerC": None,
        "assumedCop": None,
    }

    # Same "one extra lookback hour, then drop it" padding /api/nibe/history
    # uses — build_hourly_series has no baseline for its very first bucket
    # otherwise (see that function's own docstring).
    series = fetch_history_series(
        controller.base_url, controller.headers, hours_elapsed + 1, [HEAT_OFFSET_ENTITY]
    )
    if not series or not series.get(HEAT_OFFSET_ENTITY):
        return empty_response

    end_utc = now_local.astimezone(UTC)
    start_utc = midnight_local.astimezone(UTC)
    rows = build_hourly_series(series, start_utc - timedelta(hours=1), end_utc)[1:]
    if not rows:
        return empty_response

    try:
        today_prices_ore = [
            p * 100 for p in bess_controller.system.price_manager.get_buy_prices()
        ]
    except Exception as e:
        logger.debug("Could not read today's prices for Nibe savings estimate: %s", e)
        today_prices_ore = []

    periods_per_hour = time_utils.PERIODS_PER_HOUR
    hourly_inputs: list[tuple[str, float | None, float | None]] = []
    for row in rows:
        bucket_end_local = datetime.fromisoformat(row["timestamp"]).astimezone(tz)
        # build_hourly_series timestamps a bucket by its END — the hour of
        # day this bucket actually COVERS is one hour earlier.
        hour_of_day = (bucket_end_local.hour - 1) % 24
        start_period = hour_of_day * periods_per_hour
        end_period = start_period + periods_per_hour
        quarter_prices = today_prices_ore[start_period:end_period]
        price_ore = sum(quarter_prices) / len(quarter_prices) if quarter_prices else None
        hourly_inputs.append((row["timestamp"], row.get(HEAT_OFFSET_ENTITY), price_ore))

    estimate = estimate_reduction_savings(hourly_inputs)

    return {
        "hours": [
            {
                "timestamp": hour.timestamp,
                "offsetC": hour.offset_c,
                "priceOrePerKwh": hour.price_ore_per_kwh,
                "active": hour.active,
                "avoidedKwh": hour.avoided_kwh,
                "savingsKr": hour.savings_kr,
            }
            for hour in estimate.hours
        ],
        "totalAvoidedKwh": estimate.total_avoided_kwh,
        "totalSavingsKr": estimate.total_savings_kr,
        "activeHours": estimate.active_hours,
        "heatLossCoefficientKwPerC": estimate.heat_loss_coefficient_kw_per_c,
        "assumedCop": estimate.assumed_cop,
    }


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
