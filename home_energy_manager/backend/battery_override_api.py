"""API endpoints for core.bess.battery_override — the manual force-charge
override and anti-dormancy wake-up pulses (Fas 6, 2026-10-09). Same
zero-extra-I/O contract as governor_api.py/ev_scheduler_api.py: never
touches Home Assistant directly, only reflects settings_store
(battery_override.*) and BESSController.system's own cached
_battery_override_last_decision/_anti_dormancy_pulse_until state — whatever
the background poll (app.py's _poll_battery_override, every 30s) most
recently decided and acted on.

POST /api/battery/override and POST /api/battery/override/cancel are the
only writes this router does, and each is deliberately narrow — the same
"ask settings_store to request/clear a flag; _poll_battery_override is the
only thing that ever acts on it" split as ev_scheduler_api.py's own
override endpoint (see that file's docstring for the general reasoning).
"""

import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter()

# Bounds for the duration a manual override can request — confirmed with
# Håkan 2026-10-09 (30/60/120 minute dashboard choices). A plain int bound
# rather than exactly {30, 60, 120} so a slightly different duration
# entered by hand (or a future free-entry UI) isn't arbitrarily rejected.
MIN_OVERRIDE_MINUTES = 1
MAX_OVERRIDE_MINUTES = 240


def _status_payload(bess_controller: Any) -> dict:
    """Shared response shape for both status and the two write endpoints
    below, so a button's response can update the UI immediately without a
    second round-trip to GET /api/battery/override/status."""
    try:
        settings = bess_controller.settings_store.get_section("battery_override")
    except Exception as e:
        logger.error(f"Error reading battery_override settings: {e}")
        settings = {}

    system = bess_controller.system
    decision = getattr(system, "_battery_override_last_decision", None)

    return {
        "overrideForceChargeUntil": settings.get("override_force_charge_until"),
        "antiDormancyEnabled": settings.get("anti_dormancy_enabled", False),
        "antiDormancySocThreshold": settings.get("anti_dormancy_soc_threshold"),
        "antiDormancyIdleMinutes": settings.get("anti_dormancy_idle_minutes"),
        "antiDormancyPulseMinutes": settings.get("anti_dormancy_pulse_minutes"),
        # Ground truth from the last poll tick, not recomputed here — same
        # reasoning as governor_api.py/ev_scheduler_api.py's own status
        # fields: recomputing would let the dashboard show a hypothetical
        # outcome that was never actually applied.
        "active": decision.active if decision is not None else False,
        "reason": decision.reason if decision is not None else "none",
        "until": decision.until.isoformat() if decision and decision.until else None,
    }


@router.get("/api/battery/override/status")
async def get_battery_override_status() -> dict:
    """Return the current override/anti-dormancy settings and the last
    poll tick's decision.

    ``active``/``reason``/``until`` are "none"/False/null before the very
    first tick since startup — a normal state, not an error, same as
    governor_api.py's/ev_scheduler_api.py's equivalent fields.
    """
    from app import bess_controller

    return _status_payload(bess_controller)


@router.post("/api/battery/override")
async def request_battery_force_charge(body: dict) -> dict:
    """Request a manual force-charge-from-grid override for `minutes`.

    Sets battery_override.override_force_charge_until in settings_store to
    now + minutes. The next poll tick (_poll_battery_override) picks it up
    and starts writing grid_charge=True directly to hardware; it clears
    itself (this endpoint is not involved in clearing) once the duration
    elapses or the battery reaches its configured SOC ceiling, whichever
    comes first — see core/bess/battery_override.py's module docstring.

    Calling this again while an override is already active simply replaces
    the expiry with a fresh one — there is no accumulation.
    """
    from app import bess_controller

    minutes = body.get("minutes")
    if (
        not isinstance(minutes, (int, float))
        or isinstance(minutes, bool)
        or not (MIN_OVERRIDE_MINUTES <= minutes <= MAX_OVERRIDE_MINUTES)
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"minutes must be between {MIN_OVERRIDE_MINUTES} and "
                f"{MAX_OVERRIDE_MINUTES}"
            ),
        )

    from core.bess import time_utils

    until = time_utils.now() + datetime.timedelta(minutes=minutes)

    settings = bess_controller.settings_store.get_section("battery_override")
    settings["override_force_charge_until"] = until.isoformat()
    bess_controller.settings_store.save_section("battery_override", settings)

    logger.info(
        "Manual force-charge override requested: {} minutes, until {}",
        minutes,
        until.isoformat(),
    )

    return _status_payload(bess_controller)


@router.post("/api/battery/override/cancel")
async def cancel_battery_force_charge() -> dict:
    """Cancel an active (or pending) manual force-charge override.

    Clears battery_override.override_force_charge_until in settings_store.
    Takes effect on the next poll tick — up to ~30s, same latency as the
    override taking effect in the first place. A no-op (not an error) if
    no override was active.
    """
    from app import bess_controller

    settings = bess_controller.settings_store.get_section("battery_override")
    settings["override_force_charge_until"] = None
    bess_controller.settings_store.save_section("battery_override", settings)

    logger.info("Manual force-charge override cancelled")

    return _status_payload(bess_controller)
