"""API endpoint(s) for core.governor — the peak-power (EV + Nibe effektvakt)
governor.

Same reasoning as perific_api.py for being its own small file: this is the
governor's whole visible API surface, easy to find as one piece.

Deliberately zero I/O: this endpoint never touches Home Assistant. It only
reflects settings_store (governor.enabled/target_kw, nibe.effektvakt_*) and
BESSController.governor_last_decision/nibe_effektvakt_last_decision —
whatever the background poll (app.py's _poll_peak_governor, every 30s)
most recently decided and acted on. Recomputing a fresh decision here
instead would mean the dashboard could show a hypothetical outcome that
was never actually applied; showing the real last-applied decision is the
more honest choice, and it costs nothing extra since no HA reads are
needed to serve it.
"""

from fastapi import APIRouter
from loguru import logger

router = APIRouter()


@router.get("/api/governor/status")
async def get_governor_status():
    """Return the peak governor's current settings and last decision for
    both levers.

    Response shape (camelCase, matches the rest of the API):
        {
          "enabled": true, "targetKw": 12.0,
          "status": "within_budget", "reason": "...", "recentPeakKw": 9.8,
          "nibeEffektvakt": {
            "enabled": false, "baselineKw": 3.0, "floorKw": 1.0,
            "status": None, "reason": None, "currentKw": None
          }
        }
        {"enabled": false, "targetKw": 12.0, "status": None, "reason": None, "recentPeakKw": None, "nibeEffektvakt": {...}}

    Top-level ``status``/``reason`` are null whenever the EV governor is
    disabled (the 30s poll no-ops entirely and clears the last decision —
    see app.py) or hasn't ticked yet since startup. That's a normal state,
    not an error.

    ``recentPeakKw`` (added 2026-09-03) is the highest current_kw the
    governor's own poll has seen since it was last switched on — pure
    context for judging target_kw against real household draw, not
    something the governor acts on. Null under the exact same conditions
    as status/reason (see app.py's governor_recent_peak_kw comment).

    ``nibeEffektvakt`` (added 2026-10-06) mirrors the same shape for the
    second lever: null ``status``/``reason`` whenever either the EV
    governor above is off (the Nibe lever's premise doesn't exist without
    it) or its own ``enabled`` toggle is off — see
    decide_nibe_effektvakt()'s "disabled" status in
    core/governor/peak_governor.py. ``currentKw`` is the cached
    effektvakt_current_kw reading from the last poll tick (not a fresh HA
    call here — see this module's own zero-I/O docstring above),
    independent of whether the lever itself is enabled — same "read
    regardless, decide conditionally" split as the rest of this app.
    """
    from app import bess_controller

    try:
        governor_settings = bess_controller.settings_store.get_section("governor")
    except Exception as e:
        logger.error(f"Error reading governor settings: {e}")
        governor_settings = {}

    try:
        nibe_settings = bess_controller.settings_store.get_section("nibe")
    except Exception as e:
        logger.error(f"Error reading nibe settings: {e}")
        nibe_settings = {}

    decision = bess_controller.governor_last_decision
    nibe_decision = bess_controller.nibe_effektvakt_last_decision

    return {
        "enabled": governor_settings.get("enabled", False),
        "targetKw": governor_settings.get("target_kw"),
        "status": decision.status if decision is not None else None,
        "reason": decision.reason if decision is not None else None,
        "recentPeakKw": bess_controller.governor_recent_peak_kw,
        "nibeEffektvakt": {
            "enabled": nibe_settings.get("effektvakt_governor_enabled", False),
            "baselineKw": nibe_settings.get("effektvakt_baseline_kw"),
            "floorKw": nibe_settings.get("effektvakt_floor_kw"),
            "status": nibe_decision.status if nibe_decision is not None else None,
            "reason": nibe_decision.reason if nibe_decision is not None else None,
            "currentKw": bess_controller.nibe_effektvakt_last_current_kw,
        },
    }
