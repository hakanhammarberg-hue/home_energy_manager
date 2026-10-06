"""core.governor.peak_governor — the real-time EV-charging and Nibe-effektvakt
power cap decision logic.

STATUS: Fas 3b, EV lever only (2026-08-30). Pure decision function only —
no HA calls, no polling loop live here yet (that's the next Fas 3b
increment: a background job in app.py that reads PerificReader +
ZaptecController every ~30s, calls decide() below, and applies whatever it
returns). This module is deliberately free of any I/O so its logic can be
tested completely in isolation, the same way core.bess's DP algorithm is
tested separately from ha_api_controller.

WHAT THIS PORTS, AND WHAT IT DELIBERATELY LEFT OUT UNTIL NOW
    Ported from the original peak_power_governor.py's Lever 1 (EV charging
    current, slew-limited toward a floor, pause below the floor). NOT
    ported at first: Lever 2 (blocking the Nibe electric addition after
    NIBE_LEVER_DELAY_CYCLES of sustained overshoot) — the LilyGO/ESPHome
    gateway that exposes the Nibe effektvakt registers wasn't installed
    yet (see core/nibe's own status, and core/governor/__init__.py).

    Added 2026-10-06 (Håkan's explicit go-ahead, after confirming he'd
    manually set the pump's own effektvakt baseline to 3.0kW and that a
    1.0kW floor is acceptable): decide_nibe_effektvakt() below, a second
    lever mirroring the original's Lever 2 — but proportional (a
    continuous kW cap, see core/nibe/controller.py's EFFEKTVAKT tier)
    rather than the original's binary block switch
    (switch.nibe_electric_addition_blocked, an entity never confirmed to
    exist on Håkan's real installation). See that function's own
    docstring for the full design.

WHAT THE ORIGINAL SCRIPT'S WATCHDOG COVERED, AND WHAT STILL DOESN'T
    The original pyscript's 3-minute HA-core watchdog timer
    (timer.peak_governor_safety + its standalone force-restore automation
    in peak_governor_helpers.yaml) existed because blocking the Nibe
    electric addition is a real comfort/safety restriction if it got
    stuck — see the original script's own docstring, "WHAT HAPPENS IF
    HOME ASSISTANT GOES DOWN". decide_nibe_effektvakt() below has its own
    in-process watchdog (seconds_since_last_nibe_contact, mirroring
    core/nibe/decision.py's DEFAULT_WATCHDOG_TIMEOUT_S pattern) that
    forces the cap back to baseline if this add-on hasn't confirmed a
    live read from the pump in NIBE_WATCHDOG_TIMEOUT_S. That covers "this
    add-on is running but can't reach Home Assistant/the pump" — it does
    NOT cover "this add-on's own process has died or the container has
    stopped," which an in-process check can never detect by definition
    (no code runs to check anything). The original script ran *inside*
    Home Assistant's pyscript integration, so for it that failure mode
    was narrower; this add-on runs as its own Supervisor-managed
    container and can die independently of HA. The Supervisor-level
    watchdog toggle (Settings → this app → "Watchdog", currently off per
    ha_get_app) would restart the container automatically if it crashes
    — turning that on is the cheapest available mitigation today. A full
    HA-side timer+automation safety net (mirroring
    peak_governor_helpers.yaml, independent of this add-on's own process)
    would close the gap completely but is a separate build, not included
    here — flagged, not solved, same as every other known gap in this
    file's history gets written down rather than silently shipped.

    The EV-only lever's own reasoning still applies to it specifically: a
    stuck-low EV charging current is "just an inconvenience... not a
    safety concern" (the original script's own words), so it alone never
    needed a dead-man's timer. The Nibe lever is different — a stuck-low
    electric-addition cap during a cold snap is a real comfort/safety
    matter — which is exactly why it gets its own watchdog below and the
    EV lever still doesn't.

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

# Nibe effektvakt lever (added 2026-10-06) — confirmed real values from the
# same conversation as the code: Håkan's own words were "som lägst 1 kw
# låter bra" (the floor) and "3kw-värdet har jag satt som en spärr på pumpen
# manuellt, det stämmer" (the baseline — i.e. this is NOT a guess like the
# old, now-removed nibe.effektvakt_max_power_kw setting was; it is what he
# has actually dialled in on the pump's own panel). Mirrors the original
# pyscript's NIBE_LEVER_DELAY_CYCLES=3 exactly (see peak_power_governor.py,
# claude/peak_power_governor.py) — no reason found to deviate from a value
# Håkan already approved once.
NIBE_LEVER_DELAY_CYCLES = 3  # consecutive 30s cycles of "EV at floor, still over budget" before touching Nibe
NIBE_EFFEKTVAKT_FLOOR_KW = 1.0  # Håkan's explicit floor, 2026-10-06
NIBE_EFFEKTVAKT_STEP_DOWN_KW = 0.5  # per cycle — half the EV lever's proportional pace (3kW span vs. 10A span)
NIBE_EFFEKTVAKT_STEP_UP_KW = 0.25  # restore more cautiously than throttle, same ratio as RESTORE_STEP_A/CURRENT_STEP_A below
NIBE_WATCHDOG_TIMEOUT_S = 900  # mirrors core/nibe/decision.py's DEFAULT_WATCHDOG_TIMEOUT_S exactly — same 15-minute bar

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


@dataclass(frozen=True)
class NibeEffektvaktDecision:
    """What the Nibe effektvakt lever wants to happen this cycle.

    Same "description of intent, not an action" contract as
    GovernorDecision above — the caller applies effektvakt_target_kw via
    NibeController.set_effektvakt_max_power_kw() (itself gated by that
    controller's own test_mode) and is responsible for maintaining
    over_budget_streak and seconds_since_last_nibe_contact across calls,
    since this function stays pure/stateless like decide() above.
    """

    status: str  # "disabled" | "no_data" | "within_budget" | "throttling_nibe" | "watchdog_reset"
    effektvakt_target_kw: float | None  # None = don't touch the register this cycle
    reason: str


def decide_nibe_effektvakt(
    *,
    enabled: bool,
    over_budget_streak: int,
    effektvakt_current_kw: float | None,
    effektvakt_baseline_kw: float | None,
    seconds_since_last_nibe_contact: float | None,
    delay_cycles: int = NIBE_LEVER_DELAY_CYCLES,
    floor_kw: float = NIBE_EFFEKTVAKT_FLOOR_KW,
    step_down_kw: float = NIBE_EFFEKTVAKT_STEP_DOWN_KW,
    step_up_kw: float = NIBE_EFFEKTVAKT_STEP_UP_KW,
    watchdog_timeout_s: float = NIBE_WATCHDOG_TIMEOUT_S,
) -> NibeEffektvaktDecision:
    """Decide what (if anything) to change about the pump's effektvakt cap
    this cycle — the second, slower lever behind decide() above.

    Design (confirmed with Håkan 2026-10-06):
        The EV lever (decide() above) is always tried first and alone. Only
        once it has been at-or-below ZAPTEC_FLOOR_CURRENT AND the household
        is still over budget for `delay_cycles` consecutive 30s cycles in a
        row — tracked by the caller as over_budget_streak, exactly the same
        semantics as the original pyscript's _over_budget_streak — does this
        function start lowering the Nibe effektvakt cap, in step_down_kw
        steps per cycle, down to floor_kw. The moment the streak drops back
        below delay_cycles (EV alone is coping again, or the household is
        back under budget), this restores step_up_kw per cycle back toward
        effektvakt_baseline_kw — the value Håkan has manually dialled in on
        the pump's own panel (confirmed 3.0kW, 2026-10-06), NOT a hardcoded
        constant, so if he changes it at the pump later this lever follows
        along the next time he also updates the matching setting.

    Args:
        enabled: nibe.effektvakt_governor_enabled from settings. False is
            the shipped default — this function still runs every cycle
            when False (cheap, pure), but always returns "disabled" and
            never asks the caller to write anything.
        over_budget_streak: consecutive cycles (as counted by the caller —
            see app.py's _poll_peak_governor) where current_kw > target_kw
            AND the EV lever's own current reading was already at/below its
            floor. Resets to 0 the moment either condition stops holding.
        effektvakt_current_kw: live number.max_int_add_power_47212 reading,
            or None if effektvakt is unavailable (e.g. never turned on at
            the pump's own panel — see core/nibe/controller.py). No action
            is possible without this.
        effektvakt_baseline_kw: nibe.effektvakt_baseline_kw from settings —
            what Håkan has set at the pump's panel. None means not
            configured; same no-op outcome as effektvakt_current_kw being
            None, since there is nothing to restore toward.
        seconds_since_last_nibe_contact: NibeController.seconds_since_last_contact(),
            or None if no successful pump read has happened yet since this
            process started (startup grace — never a timeout by itself,
            same convention as core/nibe/decision.py's own watchdog).
    """
    if not enabled:
        return NibeEffektvaktDecision(
            status="disabled",
            effektvakt_target_kw=None,
            reason="effektvakt governor disabled in settings",
        )

    if effektvakt_current_kw is None or effektvakt_baseline_kw is None:
        return NibeEffektvaktDecision(
            status="no_data",
            effektvakt_target_kw=None,
            reason=(
                "effektvakt register unavailable or baseline not configured — "
                "nothing to adjust"
            ),
        )

    # Watchdog: only meaningful (and only fires) while the cap is actually
    # suppressed below baseline right now — if it's already at baseline
    # there is nothing stuck to force back, so a stale read alone shouldn't
    # manufacture a status change. Forces the FULL jump back to baseline in
    # one step, deliberately not step_up_kw-limited — same "when in doubt,
    # give comfort/safety margin back immediately" choice decision.py's own
    # watchdog_reset makes for the curve offset.
    if (
        seconds_since_last_nibe_contact is not None
        and seconds_since_last_nibe_contact >= watchdog_timeout_s
        and effektvakt_current_kw < effektvakt_baseline_kw
    ):
        return NibeEffektvaktDecision(
            status="watchdog_reset",
            effektvakt_target_kw=effektvakt_baseline_kw,
            reason=(
                f"no confirmed pump contact for "
                f"{seconds_since_last_nibe_contact:.0f}s "
                f"(>= {watchdog_timeout_s:.0f}s) while suppressed to "
                f"{effektvakt_current_kw:.2f}kW — forcing back to "
                f"baseline {effektvakt_baseline_kw:.2f}kW"
            ),
        )

    if over_budget_streak >= delay_cycles:
        new_target = max(floor_kw, effektvakt_current_kw - step_down_kw)
        if new_target >= effektvakt_current_kw:
            # Already at (or below, from a manual panel change) the floor —
            # nothing left to lower. Still report "throttling_nibe" so the
            # dashboard/API reflects that the lever is engaged, just maxed
            # out, rather than silently looking idle.
            return NibeEffektvaktDecision(
                status="throttling_nibe",
                effektvakt_target_kw=None,
                reason=(
                    f"EV alone insufficient for {over_budget_streak} cycles, "
                    f"effektvakt already at floor {effektvakt_current_kw:.2f}kW "
                    "— nothing more to give"
                ),
            )
        return NibeEffektvaktDecision(
            status="throttling_nibe",
            effektvakt_target_kw=new_target,
            reason=(
                f"EV alone insufficient for {over_budget_streak} cycles "
                f"(>= {delay_cycles}) — lowering effektvakt cap "
                f"{effektvakt_current_kw:.2f}kW -> {new_target:.2f}kW"
            ),
        )

    if effektvakt_current_kw < effektvakt_baseline_kw:
        new_target = min(effektvakt_baseline_kw, effektvakt_current_kw + step_up_kw)
        return NibeEffektvaktDecision(
            status="within_budget",
            effektvakt_target_kw=new_target,
            reason=(
                f"EV lever coping again (streak {over_budget_streak} < "
                f"{delay_cycles}) — restoring effektvakt cap "
                f"{effektvakt_current_kw:.2f}kW -> {new_target:.2f}kW"
            ),
        )

    return NibeEffektvaktDecision(
        status="within_budget",
        effektvakt_target_kw=None,
        reason=f"already at baseline {effektvakt_baseline_kw:.2f}kW — nothing to restore",
    )
