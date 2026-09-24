"""core.zaptec.scheduler — the price/SOC/solar gate for EV charging.

STATUS: Fas 5a (2026-08-31). Pure decision function only — no HA calls, no
ZaptecController calls, no polling loop live here yet (that's Fas 5b: a gate
that runs BEFORE core.governor.peak_governor.decide() in the same 30s poll
loop in backend/app.py). Mirrors that module's shape exactly, for the same
reason: this logic needs to be testable without a live inverter, a live car,
or a live price feed.

WHY A GATE IN FRONT OF peak_governor, NOT A MERGED DECISION
    peak_governor answers "how much current is safe for the house right
    now" — it knows nothing about price, SOC caps, or why a session might
    already be paused for cost reasons. Its own auto-resume fix (Fas 3b)
    turns charging back on the moment household load is back under budget,
    with no concept of "paused on purpose". If this module's decision were
    merged into peak_governor instead of gating it, that auto-resume would
    blindly restart a session this module intentionally stopped. Keeping
    them separate means Fas 5b's poll loop only calls into peak_governor at
    all when this module's charging_allowed is True — peak_governor keeps
    its existing contract untouched.

THE FIVE RULES THIS ENCODES (confirmed with Håkan 2026-08-30/31)
    1. Default EV charging cap: DEFAULT_SOC_CAP_PERCENT (60%) of car SOC.
    2. Above the cap, charging is allowed only if solar surplus exists
       (energy that would otherwise be exported) OR the spot price is at
       or below DEFAULT_LOW_PRICE_THRESHOLD_ORE (negative/very low).
    3. A manual override lifts the cap to 100% for the rest of the current
       plugged-in session only — confirmed one-shot-per-session, not a
       persistent toggle (AskUserQuestion, 2026-08-30). It resets itself
       the next time a NEW session starts (unplug -> replug), never mid-
       session and never on a timer.
    4. Never battery -> EV: if the home battery is discharging right now,
       EV charging is blocked outright, regardless of price or solar. This
       is a hard block that runs before the cap logic, not one more
       condition inside it — see _decide_plugged_in below. Rationale
       (docs/agents/bess-knowledge.md): round-trip loss, avoidable cycle-
       wear cost, and — the main one — the battery doesn't target the EV
       specifically. In LOAD_SUPPORT mode it's covering whatever total
       household load exists; letting a flexible/deferrable load like EV
       charging draw from it undermines whatever the DP actually earmarked
       that stored energy for.
    5. Below the cap: no deadline, no kWh target (v1 scope) — charge only
       during today's cheaper hours, ranked by percentile
       (DEFAULT_CHEAP_PRICE_PERCENTILE). This is the one rule without an
       explicit value from Håkan; 0.5 (the cheaper half of today's hours)
       is this module's proposed default, adjustable like peak_governor's
       DEFAULT_TARGET_KW was.

WHY MISSING DATA RESOLVES DIFFERENTLY ABOVE VS. BELOW THE CAP
    Below the cap, price ranking IS the entire decision — there's no
    separate fallback state to lean on, so missing price data has to mean
    "no_data" (don't touch), the same as peak_governor treats a missing
    power reading. Above the cap, the SOC cap itself is the existing,
    already-in-force state; solar surplus and low price are exceptions to
    it, and the burden of proof is on the exception. So missing solar or
    price data above the cap does NOT produce "no_data" — it just means
    that particular exception isn't proven, and the cap holds
    (charging_allowed=False), the same fail-closed shape peak_governor
    uses when it can't confirm a restore is safe.

Bekräftade riktiga entiteter i Håkans HA-instans, bilen "EV3" (2026-08-31 —
ersätter de tidigare Kia Niro-entiteterna, som är raderade efter bilbyte):
    sensor.ev3_ev_battery_level    — bilens SOC i %, motsvarar ev_soc_percent
    binary_sensor.ev3_ev_battery_plug   — inkopplad/ej, motsvarar plug_connected
    binary_sensor.ev3_ev_battery_charge — laddar just nu (informational, inte
                                           en indata till decide() ännu)
    button.ev3_force_refresh       — manuell refresh av integrationen
    sensor.ev3_car_battery_level   — 12V-hjälpbatteri, INTE relevant (samma
                                      distinktion som fanns för Niro)
    Growatt-sensorerna för "laddar ur just nu" (battery_discharging) och
    solöverskott (solar_surplus_kw) är inte omverifierade här ännu — de
    kommer från samma HomeAssistantAPIController/METHOD_SENSOR_MAP-läsningar
    core.bess redan använder, kopplas in i Fas 5b.
"""

from dataclasses import dataclass

DEFAULT_SOC_CAP_PERCENT = 60.0
DEFAULT_LOW_PRICE_THRESHOLD_ORE = 0.0  # öre/kWh — negative or zero spot price
DEFAULT_CHEAP_PRICE_PERCENTILE = 0.5  # cheaper half of today's known hours
DEFAULT_MIN_SOLAR_SURPLUS_KW = 0.0


@dataclass(frozen=True)
class SchedulerDecision:
    """Whether EV charging may happen at all right now.

    This is a gate, not a power-level decision — when charging_allowed is
    True, the caller (Fas 5b's poll loop) proceeds to
    core.governor.peak_governor.decide() to work out how much current is
    safe. When it's False, the caller pauses/keeps-paused the session
    without asking peak_governor. When it's None, there isn't enough data
    to say either way, and the caller must not change anything this cycle
    — same "don't touch on no_data" contract as GovernorDecision.
    """

    status: str
    # "no_data" | "not_plugged_in" | "blocked_battery_discharging"
    # | "blocked_above_cap" | "allowed_below_cap" | "allowed_override"
    # | "allowed_solar_surplus" | "allowed_low_price"
    charging_allowed: bool | None
    override_should_reset: bool
    reason: str


def decide(
    *,
    ev_soc_percent: float | None,
    plug_connected: bool | None,
    was_plug_connected: bool | None,
    override_requested: bool,
    battery_discharging: bool | None,
    solar_surplus_kw: float | None,
    spot_price_ore_per_kwh: float | None,
    today_prices_ore_per_kwh: list[float] | None = None,
    soc_cap_percent: float = DEFAULT_SOC_CAP_PERCENT,
    low_price_threshold_ore: float = DEFAULT_LOW_PRICE_THRESHOLD_ORE,
    cheap_price_percentile: float = DEFAULT_CHEAP_PRICE_PERCENTILE,
    min_solar_surplus_kw: float = DEFAULT_MIN_SOLAR_SURPLUS_KW,
) -> SchedulerDecision:
    """Decide whether EV charging may run this cycle.

    Pure function — no I/O anywhere in here. The caller reads
    ev_soc_percent/plug_connected/battery_discharging (from HA sensors),
    solar_surplus_kw/spot_price/today_prices (from the price+solar
    readings core.bess already has), was_plug_connected and
    override_requested (from whatever small piece of state Fas 5b keeps
    between polls — the plug's previous reading and the override flag a
    settings/UI action set), and applies whatever comes back.

    override_should_reset tells the caller a new plugged-in session just
    started (plug_connected is True and wasn't already known True — False
    or None both count, so a first poll after a restart doesn't trust a
    leftover flag either) and any stored override_requested flag should be
    cleared to False now — this function always treats the override as
    inactive for the cycle where that edge is detected, whatever
    override_requested says, since the caller hasn't had a chance to
    persist the reset yet.
    """
    # was_plug_connected is not True (False, or None e.g. first poll after a
    # restart) both count as "wasn't already connected" — an unknown prior
    # state must not be trusted to mean an override survives from an
    # earlier session.
    override_should_reset = plug_connected is True and was_plug_connected is not True
    effective_override = override_requested and not override_should_reset

    if plug_connected is None:
        return SchedulerDecision(
            status="no_data",
            charging_allowed=None,
            override_should_reset=override_should_reset,
            reason="plug status unavailable",
        )

    if plug_connected is False:
        return SchedulerDecision(
            status="not_plugged_in",
            charging_allowed=None,
            override_should_reset=override_should_reset,
            reason="no car plugged in, nothing to schedule",
        )

    return _decide_plugged_in(
        ev_soc_percent=ev_soc_percent,
        battery_discharging=battery_discharging,
        effective_override=effective_override,
        override_should_reset=override_should_reset,
        solar_surplus_kw=solar_surplus_kw,
        spot_price_ore_per_kwh=spot_price_ore_per_kwh,
        today_prices_ore_per_kwh=today_prices_ore_per_kwh,
        soc_cap_percent=soc_cap_percent,
        low_price_threshold_ore=low_price_threshold_ore,
        cheap_price_percentile=cheap_price_percentile,
        min_solar_surplus_kw=min_solar_surplus_kw,
    )


def _decide_plugged_in(
    *,
    ev_soc_percent: float | None,
    battery_discharging: bool | None,
    effective_override: bool,
    override_should_reset: bool,
    solar_surplus_kw: float | None,
    spot_price_ore_per_kwh: float | None,
    today_prices_ore_per_kwh: list[float] | None,
    soc_cap_percent: float,
    low_price_threshold_ore: float,
    cheap_price_percentile: float,
    min_solar_surplus_kw: float,
) -> SchedulerDecision:
    if ev_soc_percent is None or battery_discharging is None:
        return SchedulerDecision(
            status="no_data",
            charging_allowed=None,
            override_should_reset=override_should_reset,
            reason="EV SOC or battery-discharging reading unavailable",
        )

    # Rule 4 — hard block, checked first, overrides price/solar/override.
    if battery_discharging:
        return SchedulerDecision(
            status="blocked_battery_discharging",
            charging_allowed=False,
            override_should_reset=override_should_reset,
            reason="home battery is discharging right now — never battery -> EV",
        )

    if ev_soc_percent < soc_cap_percent:
        return _decide_below_cap(
            spot_price_ore_per_kwh=spot_price_ore_per_kwh,
            today_prices_ore_per_kwh=today_prices_ore_per_kwh,
            cheap_price_percentile=cheap_price_percentile,
            override_should_reset=override_should_reset,
        )

    return _decide_at_or_above_cap(
        effective_override=effective_override,
        solar_surplus_kw=solar_surplus_kw,
        spot_price_ore_per_kwh=spot_price_ore_per_kwh,
        low_price_threshold_ore=low_price_threshold_ore,
        min_solar_surplus_kw=min_solar_surplus_kw,
        override_should_reset=override_should_reset,
    )


def _decide_below_cap(
    *,
    spot_price_ore_per_kwh: float | None,
    today_prices_ore_per_kwh: list[float] | None,
    cheap_price_percentile: float,
    override_should_reset: bool,
) -> SchedulerDecision:
    if spot_price_ore_per_kwh is None or not today_prices_ore_per_kwh:
        return SchedulerDecision(
            status="no_data",
            charging_allowed=None,
            override_should_reset=override_should_reset,
            reason="no price data to rank today's cheap hours",
        )

    threshold = _percentile(today_prices_ore_per_kwh, cheap_price_percentile)
    if spot_price_ore_per_kwh <= threshold:
        return SchedulerDecision(
            status="allowed_below_cap",
            charging_allowed=True,
            override_should_reset=override_should_reset,
            reason=(
                f"below cap, price {spot_price_ore_per_kwh:.1f} öre "
                f"<= {threshold:.1f} öre (cheapest "
                f"{cheap_price_percentile:.0%} of today)"
            ),
        )

    return SchedulerDecision(
        status="allowed_below_cap",
        charging_allowed=False,
        override_should_reset=override_should_reset,
        reason=(
            f"below cap but price {spot_price_ore_per_kwh:.1f} öre > "
            f"{threshold:.1f} öre — waiting for a cheaper hour"
        ),
    )


def _decide_at_or_above_cap(
    *,
    effective_override: bool,
    solar_surplus_kw: float | None,
    spot_price_ore_per_kwh: float | None,
    low_price_threshold_ore: float,
    min_solar_surplus_kw: float,
    override_should_reset: bool,
) -> SchedulerDecision:
    if effective_override:
        return SchedulerDecision(
            status="allowed_override",
            charging_allowed=True,
            override_should_reset=override_should_reset,
            reason="manual override active for this session — cap lifted to 100%",
        )

    if solar_surplus_kw is not None and solar_surplus_kw > min_solar_surplus_kw:
        return SchedulerDecision(
            status="allowed_solar_surplus",
            charging_allowed=True,
            override_should_reset=override_should_reset,
            reason=(
                f"above cap, but {solar_surplus_kw:.2f}kW solar surplus would "
                "otherwise be exported"
            ),
        )

    if (
        spot_price_ore_per_kwh is not None
        and spot_price_ore_per_kwh <= low_price_threshold_ore
    ):
        return SchedulerDecision(
            status="allowed_low_price",
            charging_allowed=True,
            override_should_reset=override_should_reset,
            reason=(
                f"above cap, but spot price {spot_price_ore_per_kwh:.1f} öre "
                f"<= {low_price_threshold_ore:.1f} öre threshold"
            ),
        )

    return SchedulerDecision(
        status="blocked_above_cap",
        charging_allowed=False,
        override_should_reset=override_should_reset,
        reason="at/above SOC cap, no solar surplus or low-price exception proven",
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Value at `percentile` (0..1) of `values`, nearest-rank on the sorted list."""
    ordered = sorted(values)
    index = round(percentile * (len(ordered) - 1))
    return ordered[index]
