"""API endpoint(s) for core.governor — the peak-power (EV) governor.

Same reasoning as perific_api.py for being its own small file: this is the
governor's whole visible API surface, easy to find as one piece.

Deliberately zero I/O: this endpoint never touches Home Assistant. It only
reflects settings_store (governor.enabled/target_kw) and
BESSController.governor_last_decision — whatever the background poll
(app.py's _poll_peak_governor, every 30s) most recently decided and acted
on. Recomputing a fresh decision here instead would mean the dashboard
could show a hypothetical outcome that was never actually applied; showing
the real last-applied decision is the more honest choice, and it costs
nothing extra since no HA reads are needed to serve it.
"""

from fastapi import APIRouter
from loguru import logger

router = APIRouter()


@router.get("/api/governor/status")
async def get_governor_status():
    """Return the peak governor's current settings and last decision.

    Response shape (camelCase, matches the rest of the API):
        {"enabled": true, "targetKw": 12.0, "status": "within_budget", "reason": "...", "recentPeakKw": 9.8}
        {"enabled": false, "targetKw": 12.0, "status": None, "reason": None, "recentPeakKw": None}

    ``status``/``reason`` are null whenever the governor is disabled (the
    30s poll no-ops entirely and clears the last decision — see app.py) or
    hasn't ticked yet since startup. That's a normal state, not an error.

    ``recentPeakKw`` (added 2026-09-03) is the highest current_kw the
    governor's own poll has seen since it was last switched on — pure
    context for judging target_kw against real household draw, not
    something the governor acts on. Null under the exact same conditions
    as status/reason (see app.py's governor_recent_peak_kw comment).
    """
    from app import bess_controller

    try:
        governor_settings = bess_controller.settings_store.get_section("governor")
    except Exception as e:
        logger.error(f"Error reading governor settings: {e}")
        governor_settings = {}

    decision = bess_controller.governor_last_decision

    return {
        "enabled": governor_settings.get("enabled", False),
        "targetKw": governor_settings.get("target_kw"),
        "status": decision.status if decision is not None else None,
        "reason": decision.reason if decision is not None else None,
        "recentPeakKw": bess_controller.governor_recent_peak_kw,
    }
