"""API endpoint(s) for the dashboard-only diagnostics added 2026-09-03,
after a live 3-day check-in on Håkan's real installation surfaced two
things the dashboard had no way to show: the battery's actual SOC cycling
range over several days, and whether BESS currently has remote-control
permission over the inverter at all.

Same one-file-per-concern reasoning as perific_api.py/governor_api.py, and
the same "zero I/O here" shape as governor_api.py: both endpoints only ever
read state that app.py's background polling (_poll_diagnostics, every 30s)
already collected, never touching Home Assistant directly on request.
"""

import time

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/diagnostics/battery-soc-range")
async def get_battery_soc_range() -> dict:
    """Return the rolling battery SOC range app.py has sampled so far.

    Response shape (camelCase, matches the rest of the API):
        {"minPercent": 10.0, "maxPercent": 63.0, "windowHours": 71.4,
         "targetWindowHours": 72.0, "sampleCount": 4213}
        {"minPercent": None, "maxPercent": None, "windowHours": 0.0,
         "targetWindowHours": 72.0, "sampleCount": 0}

    ``sampleCount: 0`` (both percents null) is the normal state right after
    startup, before the first successful SOC read — not an error.

    ``windowHours`` is the ACTUAL span currently covered by
    ``battery_soc_samples`` (now minus the oldest sample still held), not
    the target. ``battery_soc_samples`` lives only in process memory, so it
    empties on every add-on restart (an update install, a crash, a manual
    restart) and only grows back out to BATTERY_SOC_RANGE_WINDOW_SECONDS
    (app.py) over the following days — until then this is honestly a
    shorter window than the target, and reporting the fixed target here
    made the card claim "senaste 3 dygn" while actually showing barely an
    hour of post-restart data (caught 2026-09-29: Håkan noticed the shown
    range looked like it only reflected the last hour or so). The frontend
    uses ``targetWindowHours`` to label the steady-state goal and to show
    a "still filling up" note while ``windowHours`` hasn't caught up to it.
    """
    from app import BATTERY_SOC_RANGE_WINDOW_SECONDS, bess_controller

    target_window_hours = BATTERY_SOC_RANGE_WINDOW_SECONDS / 3600
    samples = bess_controller.battery_soc_samples
    if not samples:
        return {
            "minPercent": None,
            "maxPercent": None,
            "windowHours": 0.0,
            "targetWindowHours": target_window_hours,
            "sampleCount": 0,
        }

    values = [soc for _timestamp, soc in samples]
    oldest_timestamp = samples[0][0]
    actual_window_hours = min((time.time() - oldest_timestamp) / 3600, target_window_hours)
    return {
        "minPercent": min(values),
        "maxPercent": max(values),
        "windowHours": actual_window_hours,
        "targetWindowHours": target_window_hours,
        "sampleCount": len(values),
    }


@router.get("/api/diagnostics/inverter-write-access")
async def get_inverter_write_access() -> dict:
    """Return whether BESS currently has remote-control permission over
    the inverter, per the last _poll_diagnostics tick.

    Response shape (camelCase, matches the rest of the API):
        {"state": "Enabled", "available": true}
        {"state": None, "available": false}

    ``available: false`` covers both "not read yet since startup" and the
    entity being unavailable/unknown right now — both a normal "no data"
    state for the dashboard to show calmly, not an error. This is a raw
    Growatt/solax-specific select state (see INVERTER_VPP_REMOTE_CONTROL_ENTITY
    in app.py) — no capability abstraction behind it yet, so a future
    inverter-platform change could make this stop reflecting anything
    meaningful without any code here noticing.
    """
    from app import bess_controller

    state = bess_controller.inverter_write_access_state
    return {"state": state, "available": state is not None}
