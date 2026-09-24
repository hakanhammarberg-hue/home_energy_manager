"""core.nibe.decision — pure decision logic for the Nibe F750's two comfort
levers: space-heating curve-offset boost and DHW ("Lyxläge varmvatten")
luxury mode.

STATUS: Fas 4a (2026-09-20, revised 2026-09-22). Mirrors core.zaptec.scheduler's
shape exactly: pure functions, no HA, no NibeController calls, testable
without a live pump.

MECHANISM CHOICE — REVISED 2026-09-22 (second pivot; read this before the
old SG Ready references elsewhere in this package's history)
    The original Fas 4a design (SG Ready) was itself a pivot away from an
    even earlier curve-offset plan, on the theory that SG Ready sidesteps
    an unconfirmed defrost-interaction risk that direct curve writes might
    carry. Live investigation against Håkan's actual F750 (2026-09-22)
    found the SG Ready plan doesn't work on his hardware at all:

    - `switch.sg_ready_heating_*` / `switch.sg_ready_hot_water_*` are NOT
      actuators. They are per-function opt-in flags ("does this function
      respond to SG Ready when SG Ready is active") with zero effect
      unless the pump's actual SG Ready *condition* — derived from TWO
      physical relay-driven inputs, `sensor.sg_ready_input_a_44878` and
      `_input_b_44879`, combined into `sensor.state_sg_ready_44874` — is
      something other than Normal. Confirmed via Håkan's own 652-entity
      device dump and cross-checked against two Home Assistant Community
      threads describing the same F-series mechanism (one using Shelly
      relays to drive the two AUX inputs; one describing a *different*,
      newer firmware's software-only alternative that Håkan's unit does
      not have).
    - Håkan has no relay hardware wired to two AUX terminals, and pump
      menu 5.1 only lets you *assign* AUX 1/2 to a function — assigning SG
      Ready to a single AUX does nothing; it takes both, physically
      wired, to produce anything other than the default Normal state.
      This directly answers the AUX question Håkan asked (2026-09-22):
      it doesn't matter which single AUX you'd pick, because one isn't
      enough regardless.

    Given that, this module now targets **`number.heat_offset_s1_47011`**
    ("Heat Offset S1") directly — a genuine Modbus-writable curve-offset
    register for climate system 1, confirmed live on Håkan's pump (reads
    "0.0", range -10..+10, step 1) once enabled in the entity registry.
    This is actually the ORIGINAL pre-SG-Ready plan, reinstated after
    re-examining the defrost concern that displaced it: that concern was
    specifically about `switch.allow_heating_47371 = off` disabling the
    compressor outright (plausibly interfering with defrost cycling) —
    curve-offset touches neither that switch nor anything that disables
    heating; it only nudges the heat curve the pump's own control loop
    already runs on top of, the same way turning the physical curve-offset
    dial in the pump's own menu would. No known defrost interaction.
    Deliberately kept conservative (see MAX_SAFE_HEAT_OFFSET_C below)
    precisely because it's a real curve register, not a purpose-built
    external-control interface like SG Ready would have been.

    CAVEAT UNCHANGED FROM THE SG READY PLAN: going over Modbus/software
    means this path has no hardware fail-safe revert-on-disconnect — see
    controller.py's docstring. A watchdog is still a hard requirement
    before this runs beyond demo mode.

    True two-relay SG Ready remains available as a *future* upgrade path
    if Håkan ever wants to wire physical AUX relays (tracked in the status
    doc, not in code) — nothing here forecloses it, this module just
    doesn't depend on it.

TWO LEVERS, ONE SHARED SIGNAL SHAPE
    decide_heating_boost() — space-heating comfort boost via
        number.heat_offset_s1_47011 (see MECHANISM CHOICE above). The
        scenario Håkan described directly: the pump works up a bit of
        extra heat during a cheap or sunny afternoon, and coasts on it
        through an expensive evening. heat_offset_c is +MAX_SAFE_HEAT_OFFSET_C
        while boosting, 0 (the pump's own neutral) otherwise — never the
        full -10..+10 range the register technically allows.
    decide_dhw_luxury() — the "Lyxläge varmvatten" dashboard toggle: when
        switched on, sets DHW comfort to Luxury whenever (cheap price OR
        solar surplus) AND the peak governor currently has headroom;
        otherwise Economy — not Normal. Economy, not Normal, was Håkan's
        own open question in the design doc, resolved here in Economy's
        favour: his own stated rule is "Kostnadsbesparingen är alltid
        prioritet ett" (cost savings is always priority one), and Normal
        would leave money on the table outside the luxury window for no
        benefit over Economy.

    Both share the same cheap-price/solar-surplus exception shape as
    core.zaptec.scheduler's above-cap logic, and the same "burden of proof
    on the exception" contract: missing price/solar data does not stall
    the decision — it just means the boost/luxury exception isn't proven,
    and the safe default (0 offset / Economy) holds.

WHY BOTH LEVERS CHECK GOVERNOR HEADROOM THEMSELVES
    Håkan's own framing: "Dock alltid med effektvakt i åtanke, den ska inte
    överstigas om den spaken är tillkopplad" — the luxury boost must check
    the fuse budget BEFORE acting, not rely on core.governor.peak_governor
    to throttle it after the fact. Nibe has no lever in peak_governor at
    all (see core/governor/__init__.py's "MEDVETET INTE MED I DEN HÄR
    FASEN" note) — this module is what makes that omission safe: it treats
    the governor's configured target_kw and the latest Perific reading as
    an input, not an override reconciled downstream. Applied to BOTH
    levers, not just DHW as Håkan's own phrasing might suggest read
    literally — any lever that can increase electrical draw needs the same
    check, or "never exceed a connected effektvakt" only holds for half of
    this module's writes.

    Missing headroom data (governor enabled but no recent Perific reading)
    resolves to "no headroom" — the opposite default from the price/solar
    exception above, because here the stakes of being wrong run the other
    way: guessing "there's room" on missing data could exceed a real fuse
    limit, while guessing "no room" only costs a missed comfort/savings
    window.
"""

from dataclasses import dataclass

DEFAULT_CHEAP_PRICE_PERCENTILE = 0.5  # cheaper half of today's known hours — same default as core.zaptec.scheduler
DEFAULT_MIN_SOLAR_SURPLUS_KW = 0.0
DEFAULT_HEADROOM_MARGIN_KW = 0.0  # v1 scope: any positive headroom counts, no safety buffer beyond target_kw itself

# The register (number.heat_offset_s1_47011) allows -10..+10 in steps of 1,
# but this module only ever asks for a small, conservative nudge — not the
# full range a person adjusting the pump's own menu might use. +2 was
# chosen as "noticeably more heat, nowhere near an aggressive setting";
# revisit only after a season of real (demo_mode=False) data, not on a
# guess.
DEFAULT_HEAT_OFFSET_BOOST_C = 2
MAX_SAFE_HEAT_OFFSET_C = 2  # decision-layer ceiling; controller.py clamps again, defense in depth


@dataclass(frozen=True)
class HeatingBoostDecision:
    """Whether the space-heating curve-offset lever should be engaged this cycle.

    status: "no_data" | "no_headroom" | "engaged_cheap_price" |
        "engaged_solar_surplus" | "normal"
    heat_offset_c: the value to write to number.heat_offset_s1_47011 —
        DEFAULT_HEAT_OFFSET_BOOST_C while boosting, 0 for Normal, None
        only for no_data (don't touch the register at all that cycle).
    """

    status: str
    heat_offset_c: int | None
    reason: str


@dataclass(frozen=True)
class DhwLuxuryDecision:
    """Whether DHW should be in Luxury or Economy comfort mode this cycle.

    status: "disabled" | "no_headroom" | "luxury_cheap_price" |
        "luxury_solar_surplus" | "economy_no_condition"
    comfort_mode: "luxury" | "economy" | None (None only when disabled —
        the caller must leave the register untouched entirely, the same
        "off = don't even read" contract governor/ev_scheduler use for
        their own enabled flags).
    """

    status: str
    comfort_mode: str | None
    reason: str


def _headroom_available(
    *,
    governor_enabled: bool,
    current_kw: float | None,
    target_kw: float | None,
    margin_kw: float,
) -> bool | None:
    """Shared headroom check for both levers.

    Returns True/False, or None if the governor is enabled but the inputs
    needed to judge headroom aren't available this cycle. None here means
    "can't prove there's room", not "there is room" — callers fail closed.
    """
    if not governor_enabled:
        # No fuse cap configured/active at all — nothing to protect against.
        return True
    if current_kw is None or target_kw is None:
        return None
    return (target_kw - current_kw) > margin_kw


def decide_heating_boost(
    *,
    spot_price_ore_per_kwh: float | None,
    today_prices_ore_per_kwh: list[float] | None,
    solar_surplus_kw: float | None,
    governor_enabled: bool,
    current_kw: float | None,
    target_kw: float | None,
    cheap_price_percentile: float = DEFAULT_CHEAP_PRICE_PERCENTILE,
    min_solar_surplus_kw: float = DEFAULT_MIN_SOLAR_SURPLUS_KW,
    headroom_margin_kw: float = DEFAULT_HEADROOM_MARGIN_KW,
    heat_offset_boost_c: int = DEFAULT_HEAT_OFFSET_BOOST_C,
) -> HeatingBoostDecision:
    """Pure decision for the space-heating curve-offset comfort-boost lever."""
    headroom = _headroom_available(
        governor_enabled=governor_enabled,
        current_kw=current_kw,
        target_kw=target_kw,
        margin_kw=headroom_margin_kw,
    )
    if headroom is None:
        return HeatingBoostDecision(
            status="no_data",
            heat_offset_c=None,
            reason="peak governor is on but household power reading is unavailable",
        )
    if headroom is False:
        return HeatingBoostDecision(
            status="no_headroom",
            heat_offset_c=0,
            reason="peak governor has no headroom right now — staying at neutral offset",
        )

    if solar_surplus_kw is not None and solar_surplus_kw > min_solar_surplus_kw:
        return HeatingBoostDecision(
            status="engaged_solar_surplus",
            heat_offset_c=heat_offset_boost_c,
            reason=(
                f"{solar_surplus_kw:.2f}kW solar surplus would otherwise be "
                f"exported — boosting heat curve by +{heat_offset_boost_c}"
            ),
        )

    if spot_price_ore_per_kwh is not None and today_prices_ore_per_kwh:
        threshold = _percentile(today_prices_ore_per_kwh, cheap_price_percentile)
        if spot_price_ore_per_kwh <= threshold:
            return HeatingBoostDecision(
                status="engaged_cheap_price",
                heat_offset_c=heat_offset_boost_c,
                reason=(
                    f"price {spot_price_ore_per_kwh:.1f} öre <= {threshold:.1f} öre "
                    f"(cheapest {cheap_price_percentile:.0%} of today) — boosting heat "
                    f"curve by +{heat_offset_boost_c}"
                ),
            )

    return HeatingBoostDecision(
        status="normal",
        heat_offset_c=0,
        reason="no cheap-price or solar-surplus exception proven — staying at neutral offset",
    )


def decide_dhw_luxury(
    *,
    enabled: bool,
    spot_price_ore_per_kwh: float | None,
    today_prices_ore_per_kwh: list[float] | None,
    solar_surplus_kw: float | None,
    governor_enabled: bool,
    current_kw: float | None,
    target_kw: float | None,
    cheap_price_percentile: float = DEFAULT_CHEAP_PRICE_PERCENTILE,
    min_solar_surplus_kw: float = DEFAULT_MIN_SOLAR_SURPLUS_KW,
    headroom_margin_kw: float = DEFAULT_HEADROOM_MARGIN_KW,
) -> DhwLuxuryDecision:
    """Pure decision for the "Lyxläge varmvatten" dashboard toggle.

    `enabled` is the dashboard switch itself (nibe.dhw_luxury_enabled in
    settings_store) — when off, this is a deliberate no-op: comfort_mode
    is None and the caller must not touch the register at all.
    """
    if not enabled:
        return DhwLuxuryDecision(
            status="disabled", comfort_mode=None, reason="Lyxläge varmvatten is off"
        )

    headroom = _headroom_available(
        governor_enabled=governor_enabled,
        current_kw=current_kw,
        target_kw=target_kw,
        margin_kw=headroom_margin_kw,
    )
    if headroom is not True:
        # None (can't prove) or False (proven no room) both fail closed to
        # Economy here — unlike the heating lever, DHW luxury has no
        # separate "no_data" status: Economy is always a safe, valid state
        # to write, so there's no "don't touch" case to preserve.
        reason = (
            "peak governor has no headroom right now"
            if headroom is False
            else "peak governor is on but household power reading is unavailable"
        )
        return DhwLuxuryDecision(
            status="no_headroom", comfort_mode="economy", reason=reason
        )

    if solar_surplus_kw is not None and solar_surplus_kw > min_solar_surplus_kw:
        return DhwLuxuryDecision(
            status="luxury_solar_surplus",
            comfort_mode="luxury",
            reason=(
                f"{solar_surplus_kw:.2f}kW solar surplus would otherwise be "
                "exported — Luxury hot water"
            ),
        )

    if spot_price_ore_per_kwh is not None and today_prices_ore_per_kwh:
        threshold = _percentile(today_prices_ore_per_kwh, cheap_price_percentile)
        if spot_price_ore_per_kwh <= threshold:
            return DhwLuxuryDecision(
                status="luxury_cheap_price",
                comfort_mode="luxury",
                reason=(
                    f"price {spot_price_ore_per_kwh:.1f} öre <= {threshold:.1f} öre "
                    f"(cheapest {cheap_price_percentile:.0%} of today) — Luxury hot water"
                ),
            )

    return DhwLuxuryDecision(
        status="economy_no_condition",
        comfort_mode="economy",
        reason="no cheap-price or solar-surplus exception proven — Economy hot water",
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Same nearest-rank percentile as core.zaptec.scheduler._percentile —
    duplicated rather than imported so this module has zero cross-package
    dependencies, same reasoning as peak_governor.py's own constants."""
    ordered = sorted(values)
    index = round(percentile * (len(ordered) - 1))
    return ordered[index]
