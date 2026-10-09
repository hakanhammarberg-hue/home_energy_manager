"""Manual force-charge override and anti-dormancy wake-up pulses for the
battery (Fas 6, 2026-10-09).

Motivation -- see the project's own operational log, punkt 33/34 and 40:
a chronic Growatt Modbus/WiFi reliability problem has twice let the
battery's BMS drop into a "No BMS Connected"/Dormancy state while sitting
idle at a low SOC (most visibly at the 10% floor). A hardware restart
(inverter + AC breaker + battery) brought the BMS back, but nothing in this
app would have prevented or recovered from it automatically. Håkan asked
for two related levers:

1. A manual "force-charge from grid" override -- a dashboard button that
   overrides the DP optimizer's own period-by-period plan for a chosen
   duration (30/60/120 minutes). Self-expiring: it clears itself once the
   duration elapses OR the battery reaches its configured SOC ceiling,
   whichever comes first -- no second step to remember.

2. An automatic anti-dormancy "wake-up" pulse: when SOC is already low
   (<= anti_dormancy_soc_threshold -- deliberately a single threshold that
   also covers the confirmed 10%-floor case; no separate logic needed for
   that, it is just the same mechanism at a lower SOC) AND the battery has
   sat completely idle (no charge/discharge power at all) for
   anti_dormancy_idle_minutes, force a short grid-charge pulse
   (anti_dormancy_pulse_minutes) purely to keep the BMS's own internal
   logic from deciding nothing is happening and going to sleep. Deliberately
   NOT price-aware -- a five-minute pulse costs a few öre regardless of the
   hour, and that is the right trade against a multi-day BMS outage.

Design: both levers resolve to the same primitive, grid_charge=True for a
bounded window -- see ForcedChargeDecision. The one subtlety is who is
allowed to write to hardware during that window. BatterySystemManager's own
quarterly DP-apply cycle (_apply_period_schedule, called from
update_battery_schedule) would otherwise keep reasserting its own plan
every 15 minutes and fight a forced-charge window that is active in
between -- so update_battery_schedule calls is_forced_charge_window_open()
(read-only, no side effects) to decide whether to skip its own hardware
writes for that cycle, leaving a dedicated 30s-cadence poll job
(BatterySystemManager.poll_forced_charge, called from backend/app.py's
_poll_battery_override tick, mirroring _poll_ev_charging/_poll_nibe's
cadence) as the sole writer while a window is open.

decide_forced_charge() is the one function with side-effect *flags*
(override_cleared, pulse_started) -- call it from exactly one place (that
poll job) so a clear/pulse-start is only ever acted on once. Everything
else (update_battery_schedule's own guard) uses the read-only
is_forced_charge_window_open() instead.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

# Anti-dormancy defaults, confirmed with Håkan 2026-10-09: SOC <= 15% is "low
# enough to risk dormancy" (comfortably covers the confirmed 10%-floor
# incident with margin, without engaging during ordinary daily cycling), 30
# minutes fully idle (0W both directions) before concluding this is a real
# stall and not just a brief lull between DP-planned periods, and a
# 5-minute pulse -- long enough for the BMS to see sustained current, short
# enough that even several pulses a day cost nothing material.
DEFAULT_ANTI_DORMANCY_SOC_THRESHOLD = 15.0
DEFAULT_ANTI_DORMANCY_IDLE_MINUTES = 30.0
DEFAULT_ANTI_DORMANCY_PULSE_MINUTES = 5.0

# Anything at or below this magnitude (either direction) counts as "not
# actually moving any energy" for idle-time tracking -- a real zero rarely
# survives sensor noise/rounding exactly, and this is cheap insurance
# against that without needing a separate "near enough to zero" setting.
IDLE_POWER_THRESHOLD_W = 10.0


@dataclass(frozen=True)
class ForcedChargeDecision:
    """What poll_forced_charge() should do on this tick, and what state
    changes it needs to persist/record (override_cleared/pulse_started) --
    decide_forced_charge never mutates anything itself, same pure-function
    convention as every other *_decision module in this app
    (core/nibe/decision.py, core/zaptec/scheduler.py, core/governor/
    peak_governor.py).
    """

    active: bool
    reason: str  # "manual_override" | "anti_dormancy" | "none"
    until: datetime.datetime | None
    override_cleared: bool
    pulse_started: bool


def is_forced_charge_window_open(
    *,
    now: datetime.datetime,
    soc_percent: float | None,
    max_soc_percent: float,
    override_until: datetime.datetime | None,
    pulse_until: datetime.datetime | None,
) -> bool:
    """Read-only: is a forced-charge window open right now?

    Used by update_battery_schedule's own quarterly apply cycle to decide
    whether to skip ITS hardware writes this tick (see module docstring) --
    deliberately side-effect-free and safe to call from more than one
    place, unlike decide_forced_charge below.
    """
    if override_until is not None and now < override_until:
        if soc_percent is None or soc_percent < max_soc_percent:
            return True
    if pulse_until is not None and now < pulse_until:
        return True
    return False


def decide_forced_charge(
    *,
    now: datetime.datetime,
    soc_percent: float | None,
    max_soc_percent: float,
    override_until: datetime.datetime | None,
    anti_dormancy_enabled: bool,
    last_nonzero_power_ts: datetime.datetime | None,
    pulse_until: datetime.datetime | None,
    anti_dormancy_soc_threshold: float = DEFAULT_ANTI_DORMANCY_SOC_THRESHOLD,
    anti_dormancy_idle_minutes: float = DEFAULT_ANTI_DORMANCY_IDLE_MINUTES,
    anti_dormancy_pulse_minutes: float = DEFAULT_ANTI_DORMANCY_PULSE_MINUTES,
) -> ForcedChargeDecision:
    """The one function allowed to decide a forced-charge window should
    start or end -- call it from exactly one place (the 30s poll job), not
    also from update_battery_schedule, or override_cleared/pulse_started
    could each be acted on twice for the same event.

    Manual override always takes precedence over anti-dormancy when both
    would otherwise be active on the same tick -- it is the explicit,
    deliberate one.
    """
    override_cleared = False

    if override_until is not None:
        soc_cap_reached = soc_percent is not None and soc_percent >= max_soc_percent
        time_expired = now >= override_until
        if soc_cap_reached or time_expired:
            override_cleared = True
        else:
            return ForcedChargeDecision(
                active=True,
                reason="manual_override",
                until=override_until,
                override_cleared=False,
                pulse_started=False,
            )

    # No active manual override (either there never was one, or it just
    # cleared above) -- fall through to anti-dormancy. An already-running
    # pulse is continued to completion regardless of the enabled/threshold
    # checks below (a short pulse finishing cleanly is harmless and
    # arguably correct even if a setting flipped mid-pulse).
    if pulse_until is not None and now < pulse_until:
        return ForcedChargeDecision(
            active=True,
            reason="anti_dormancy",
            until=pulse_until,
            override_cleared=override_cleared,
            pulse_started=False,
        )

    if not anti_dormancy_enabled or soc_percent is None:
        return ForcedChargeDecision(
            active=False,
            reason="none",
            until=None,
            override_cleared=override_cleared,
            pulse_started=False,
        )

    if soc_percent > anti_dormancy_soc_threshold:
        return ForcedChargeDecision(
            active=False,
            reason="none",
            until=None,
            override_cleared=override_cleared,
            pulse_started=False,
        )

    # Low enough to risk dormancy -- but only pulse once genuinely idle for
    # long enough. Missing idle-timestamp data means "can't prove it's been
    # idle" -- burden of proof on triggering a new pulse, same convention as
    # every other gate in this app (core/nibe/decision.py's degree-minutes
    # floor, indoor-temp ceiling, ...): never trigger on an unknown, only
    # ever on confirmed evidence.
    if last_nonzero_power_ts is None:
        return ForcedChargeDecision(
            active=False,
            reason="none",
            until=None,
            override_cleared=override_cleared,
            pulse_started=False,
        )

    idle_minutes = (now - last_nonzero_power_ts).total_seconds() / 60.0
    if idle_minutes < anti_dormancy_idle_minutes:
        return ForcedChargeDecision(
            active=False,
            reason="none",
            until=None,
            override_cleared=override_cleared,
            pulse_started=False,
        )

    new_pulse_until = now + datetime.timedelta(minutes=anti_dormancy_pulse_minutes)
    return ForcedChargeDecision(
        active=True,
        reason="anti_dormancy",
        until=new_pulse_until,
        override_cleared=override_cleared,
        pulse_started=True,
    )
