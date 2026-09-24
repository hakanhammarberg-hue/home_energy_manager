"""core.governor.peak_governor — the real-time EV-charging power cap decision logic.

STATUS: Fas 3b, EV lever only (2026-08-30). Pure decision function only —
no HA calls, no polling loop live here yet (that's the next Fas 3b
increment: a background job in app.py that reads PerificReader +
ZaptecController every ~30s, calls decide() below, and applies whatever it
returns). This module is deliberately free of any I/O so its logic can be
tested completely in isolation, the same way core.bess's DP algorithm is
tested separately from ha_api_controller.

WHAT THIS PORTS, AND WHAT IT DELIBERATELY LEAVES OUT
    Ported from the original peak_power_governor.py's Lever 1 (EV charging
    current, slew-limited toward a floor, pause below the floor). NOT
    ported: Lever 2 (blocking the Nibe electric addition after
    NIBE_LEVER_DELAY_CYCLES of sustained overshoot) — the LilyGO/ESPHome
    gateway that exposes that switch isn't installed yet (see
    core/nibe's own status, and core/governor/__init__.py). Nothing in
    this module references Nibe at all, so there's nothing here to
    accidentally half-wire later.

    Also not ported: the 3-minute HA-core watchdog timer
    (timer.peak_governor_safety + its standalone force-restore automation
    in peak_governor_helpers.yaml). That existed specifically because
    blocking the Nibe electric addition is a real comfort/safety
    restriction if it got stuck — see the original script's own docstring,
    "WHAT HAPPENS IF HOME ASSISTANT GOES DOWN". The EV-only lever this
    module implements doesn't have that property: the original script's
    own reasoning classes a stuck-low EV charging current as "just an
    inconvenience... not a safety concern," not something requiring a
    dead-man's timer. Revisit this the day the Nibe lever gets built —
    at that point the watchdog needs to come back, because that's what
    makes blocking the electric addition safe to leave unattended.

A FIX FROM THE ORIGINAL SCRIPT (confirmed with Håkan 2026-08-30)
    peak_power_governor.py's restore path (_restore_ev_to_normal) only
    ever raised the current number entity — it never turned
    switch.gpn049831_laddar back on after Lever 1 had paused it. In the
    original design that gap was papered over by the Nibe-only watchdog
    automation, which happens to include a switch.turn_on for the Zaptec
    switch when it fires — but that only fires when the *Nibe* lever is
    engaged and the watchdog times out, neither of which applies to an
    EV-only pause with no Nibe lever built at all. Fixed here as an
    explicit, intentional change: decide() sets resume_charging=True
    whenever household power is back under budget and the charging switch
    is currently off — so a pause this module causes is also a pause this
    module lifts, without a manual step or an unrelated subsystem's
    timeout being the only way out.

NO HYSTERESIS, ON PURPOSE (FOR NOW)
    Same as the original: the moment overshoot crosses zero, this reports
    "restore" — including a resume on the very next ~30s cycle after a
    pause. If household load hovers right at the target, pause/resume
    could flip fairly often. The original script didn't guard against
    this either, and adding a dead zone wasn't part of what was asked —
    noting it here rather than quietly building it in unasked.
"""

from dataclasses import dataclass

# Confirmed real installation values (2026-08-29) — same constants as
# core.zaptec.controller, repeated here rather than imported so this module
# stays entirely dependency-free (no HA, no requests, nothing to mock in
# tests). If these ever drift apart, that's a signal worth noticing, not
# hiding behind a shared import.
ZAPTEC_NORMAL_MAX_CURRENT = 16  # amps — 11kW/3-phase, the real installation limit
ZAPTEC_FLOOR_CURRENT = 6  # amps — matches number.gpn049831_min_laddstrom
ZAPTEC_VOLTAGE = 230  # volts per phase
ZAPTEC_PHASES = 3

CURRENT_STEP_A = 2  # max amps to move Zaptec's limit down per cycle
RESTORE_STEP_A = 1  # restore more cautiously than we throttle

# Confirmed with Håkan 2026-08-30: 20A/3-phase main fuse = 3 x 230V x 20A =
# 13.8kW theoretical max. 12kW leaves margin for other household loads
# before the fuse itself would trip on a brief combined peak. This is only
# the shipped starting point — adjustable in Settings once that UI exists
# (next increment after the polling loop).
DEFAULT_TARGET_KW = 12.0


@dataclass(frozen=True)
class GovernorDecision:
    """What the governor wants to happen this cycle.

    This is a description of intent, not an action — the caller (the
    polling loop, not built yet) is responsible for actually calling
    ZaptecController with whatever this says, and for respecting
    ZaptecController's own test_mode gate exactly like everything else
    that writes to Zaptec.
    """

    status: str  # "within_budget" | "throttling_ev" | "no_data"
    ev_current_target_a: float | None  # None = don't touch the current entity
    pause_charging: bool
    resume_charging: bool
    reason: str


def decide(
    *,
    current_kw: float | None,
    target_kw: float | None,
    ev_current_a: float | None,
    charging_switch_on: bool | None,
    normal_max_current: float = ZAPTEC_NORMAL_MAX_CURRENT,
    floor_current: float = ZAPTEC_FLOOR_CURRENT,
    current_step_a: float = CURRENT_STEP_A,
    restore_step_a: float = RESTORE_STEP_A,
    voltage: float = ZAPTEC_VOLTAGE,
    phases: int = ZAPTEC_PHASES,
) -> GovernorDecision:
    """Decide what (if anything) to change about Zaptec's charging this cycle.

    Pure function — no I/O, no HA, no ZaptecController calls anywhere in
    here. The caller reads current_kw (from PerificReader), ev_current_a
    and charging_switch_on (from ZaptecController), and target_kw (from
    settings), passes them in, and applies whatever comes back.

    Args:
        current_kw: Household power draw right now, or None if the
            Perific reading was unavailable this cycle.
        target_kw: The configured cap, or None if not yet configured.
        ev_current_a: Zaptec's current available-current setting, or None
            if that entity is unavailable (e.g. no car connected).
        charging_switch_on: Whether Zaptec's charging switch is currently
            on, True/False, or None if that entity is unavailable.
    """
    if current_kw is None or target_kw is None:
        return GovernorDecision(
            status="no_data",
            ev_current_target_a=None,
            pause_charging=False,
            resume_charging=False,
            reason="missing power reading or target setting",
        )

    overshoot_kw = current_kw - target_kw

    if overshoot_kw <= 0:
        return _decide_within_budget(
            current_kw=current_kw,
            target_kw=target_kw,
            ev_current_a=ev_current_a,
            charging_switch_on=charging_switch_on,
            normal_max_current=normal_max_current,
            restore_step_a=restore_step_a,
        )

    return _decide_over_budget(
        current_kw=current_kw,
        target_kw=target_kw,
        overshoot_kw=overshoot_kw,
        ev_current_a=ev_current_a,
        floor_current=floor_current,
        current_step_a=current_step_a,
        voltage=voltage,
        phases=phases,
    )


def _decide_within_budget(
    *,
    current_kw: float,
    target_kw: float,
    ev_current_a: float | None,
    charging_switch_on: bool | None,
    normal_max_current: float,
    restore_step_a: float,
) -> GovernorDecision:
    new_current = None
    if ev_current_a is not None and ev_current_a < normal_max_current:
        new_current = min(normal_max_current, ev_current_a + restore_step_a)

    # The fix described in the module docstring: resume whenever we're back
    # under budget and the switch is known (not just assumed) to be off.
    resume = charging_switch_on is False

    reason = f"{current_kw:.2f}kW <= {target_kw:.2f}kW target"
    if new_current is not None:
        reason += f", restoring EV current {ev_current_a:.0f}A -> {new_current:.0f}A"
    if resume:
        reason += ", resuming paused charging"
    if new_current is None and not resume:
        reason += ", nothing to restore"

    return GovernorDecision(
        status="within_budget",
        ev_current_target_a=new_current,
        pause_charging=False,
        resume_charging=resume,
        reason=reason,
    )


def _decide_over_budget(
    *,
    current_kw: float,
    target_kw: float,
    overshoot_kw: float,
    ev_current_a: float | None,
    floor_current: float,
    current_step_a: float,
    voltage: float,
    phases: int,
) -> GovernorDecision:
    if ev_current_a is None:
        return GovernorDecision(
            status="no_data",
            ev_current_target_a=None,
            pause_charging=False,
            resume_charging=False,
            reason="Zaptec current entity unavailable",
        )

    overshoot_a = (overshoot_kw * 1000) / (voltage * phases)
    wanted_current = max(0.0, ev_current_a - max(current_step_a, overshoot_a))

    if wanted_current < floor_current:
        # Below the floor isn't a valid charging current — pause instead of
        # crawling. Deliberately don't touch the current number entity here
        # (matches the original script): it stays at whatever it already
        # was, so the restore path has a sensible value to ramp up from.
        return GovernorDecision(
            status="throttling_ev",
            ev_current_target_a=None,
            pause_charging=True,
            resume_charging=False,
            reason=(
                f"{current_kw:.2f}kW over {target_kw:.2f}kW target even at "
                "floor current — pausing EV charging"
            ),
        )

    new_current = round(wanted_current)
    return GovernorDecision(
        status="throttling_ev",
        ev_current_target_a=new_current,
        pause_charging=False,
        resume_charging=False,
        reason=(
            f"{current_kw:.2f}kW over {target_kw:.2f}kW target, "
            f"EV current {ev_current_a:.0f}A -> {new_current}A"
        ),
    )
