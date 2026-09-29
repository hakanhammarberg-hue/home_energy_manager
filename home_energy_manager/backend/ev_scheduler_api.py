"""API endpoint(s) for core.zaptec.scheduler — the EV price/SOC/solar gate.

Same reasoning as governor_api.py for being its own small file, and the same
zero-I/O contract: never touches Home Assistant directly. It only reflects
settings_store (ev_scheduler.*) and BESSController.ev_scheduler_last_decision
— whatever the background poll (app.py's _poll_ev_charging, every 30s) most
recently decided and acted on. Recomputing a fresh decision here instead
would mean the dashboard could show a hypothetical outcome that was never
actually applied (see governor_api.py's docstring — same argument).

POST /api/ev-scheduler/override is the one write this router does, and it's
deliberately narrow: it only ever sets override_requested=True. Everything
else about the override (when it takes effect, when it's ignored as stale,
when it resets) is core.zaptec.scheduler.decide()'s and app.py's
_poll_ev_charging's job, not this endpoint's.
"""

from typing import Any

from fastapi import APIRouter
from loguru import logger

router = APIRouter()


def _status_payload(bess_controller: Any) -> dict:
    """Shared response shape for both endpoints below, so the override
    button's response can update the UI immediately without a second
    round-trip to GET /api/ev-scheduler/status."""
    try:
        settings = bess_controller.settings_store.get_section("ev_scheduler")
    except Exception as e:
        logger.error(f"Error reading ev_scheduler settings: {e}")
        settings = {}

    decision = bess_controller.ev_scheduler_last_decision

    return {
        "enabled": settings.get("enabled", False),
        "evSocPercent": getattr(bess_controller, "ev_scheduler_last_ev_soc_percent", None),
        "socCapPercent": settings.get("soc_cap_percent"),
        "lowPriceThresholdOre": settings.get("low_price_threshold_ore"),
        "cheapPricePercentile": settings.get("cheap_price_percentile"),
        "overrideRequested": settings.get("override_requested", False),
        "status": decision.status if decision is not None else None,
        "chargingAllowed": decision.charging_allowed if decision is not None else None,
        "reason": decision.reason if decision is not None else None,
        # Added 2026-09-29: the car's own ground truth, independent of
        # `enabled`/`status`/`chargingAllowed` above (which are all about
        # whether THIS APP is gating charging) — see app.py's
        # _poll_ev_charging for why these three are read every tick
        # regardless of the ev_scheduler feature toggle.
        "chargingActive": getattr(bess_controller, "ev_last_charging_active", None),
        "estimatedChargeDurationMin": getattr(
            bess_controller, "ev_last_charge_duration_min", None
        ),
    }


@router.get("/api/ev-scheduler/status")
async def get_ev_scheduler_status() -> dict:
    """Return the EV scheduler's current settings and last decision.

    ``status``/``chargingAllowed``/``reason`` are null whenever the
    scheduler is disabled (the price/solar charging automation itself,
    not just this endpoint) or hasn't ticked yet since startup. That's a
    normal state, not an error — same as governor_api.py's equivalent
    fields.

    ``evSocPercent``/``chargingActive``/``estimatedChargeDurationMin`` are
    different: they're the car's own reported facts, read every 30s tick
    regardless of whether the scheduler feature is enabled (see app.py's
    _poll_ev_charging) — only null before the very first tick since
    startup, or if the car itself hasn't reported that field.
    """
    from app import bess_controller

    return _status_payload(bess_controller)


@router.post("/api/ev-scheduler/override")
async def request_ev_scheduler_override() -> dict:
    """Request the one-shot cap override for the current charging session.

    Sets ev_scheduler.override_requested=True in settings_store. The next
    poll tick (_poll_ev_charging) either honors it — if a session is
    already in progress — or, if a fresh plug-in edge is detected that
    same tick, treats it as stale and resets it right back to False (see
    core/zaptec/scheduler.py's override_should_reset). This endpoint does
    not attempt to tell those two cases apart; it only ever requests.
    """
    from app import bess_controller

    settings = bess_controller.settings_store.get_section("ev_scheduler")
    settings["override_requested"] = True
    bess_controller.settings_store.save_section("ev_scheduler", settings)

    return _status_payload(bess_controller)
