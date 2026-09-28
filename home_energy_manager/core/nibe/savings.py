"""core.nibe.savings — a pure, honestly-scoped estimate of today's cost
savings from the space-heating lever's active price-peak reduction
("reduced_expensive_price", core/nibe/decision.py's FIFTH LEVER,
DEFAULT_HEAT_OFFSET_REDUCTION_C = -2).

WHY THIS EXISTS (2026-09-28): Håkan asked for a Nibe cost-savings figure on
the dashboard "likt growatt har för sitt batteri" (like Growatt has for its
battery). The battery's own Cost & Savings card (SystemStatusCard.tsx) can
do this exactly, because core.bess.dp_battery_algorithm computes a genuine
grid-only-vs-optimized kWh comparison. Nibe has no equivalent: no delivered-
heat/COP sensor, no thermal model of the house. See
claude/dashboard-compaction-and-nibe-savings-forslag.md for the full
competitive-research writeup behind the approach below — summarized here:

- Home Assistant's own proposed native heat-pump Energy Dashboard support
  (github.com/orgs/home-assistant/discussions/2917) uses COP =
  delivered_heat_kWh / electricity_kWh, which needs a delivered-heat sensor
  Håkan's F750 setup doesn't expose. Not usable here.
- No Nibe smart-control project found (tengmo-ab/smart-heat-control,
  Samot89's NIBE blueprint) computes a savings figure at all.
- The established methodology for estimating heat-pump/thermostat setback
  savings WITHOUT a full thermal model is a degree-hour proxy (see DIY Smart
  Home Hub's "Smart Thermostat Setback Savings Calculator"): avoided energy
  ~= |offset| x hours x a heat-loss-per-degree constant, converted through
  an assumed COP. That is exactly what this module does, scoped to the ONE
  lever that genuinely reduces net consumption.

DELIBERATELY EXCLUDED: the three boost branches (engaged_solar_surplus,
engaged_cheap_price, engaged_price_spike_ahead) spend MORE energy at boost
time to bank comfort for later — they shift consumption in time rather than
reduce it. Counting them as "savings" here would overclaim, so this module
only ever looks at hours where the applied offset was negative (the
reduction lever, and only that lever ever asks for less heat than neutral).

THIS IS A MODEL, NOT A MEASUREMENT. HEAT_LOSS_COEFFICIENT_KW_PER_C and
ASSUMED_COP are first guesses for a normally-insulated villa/F750, not
measured for this installation — every caller of estimate_reduction_savings
must label the result "uppskattad" (estimated) wherever it's shown, same as
Håkan asked for ("likt growatt", which itself always shows Today's Savings
as a plain figure — but Nibe's figure has no equivalent ground truth to
verify against, hence the explicit estimate framing here instead).

Pure function, no HA, no I/O — same testable-without-a-live-pump shape as
decision.py/history.py's own split of I/O (backend/nibe_api.py,
core/nibe/history.py's fetch_history_series) from calculation (here).
"""

from __future__ import annotations

from dataclasses import dataclass

# A first guess for how many kW of space-heating demand a 1 degC curve-offset
# change represents for a normally-insulated Swedish villa this size — NOT
# measured for Håkan's house. Revisit once the calibration comparison (see
# module docstring) has accumulated enough hours to say whether this over-
# or under-estimates the real effect.
DEFAULT_HEAT_LOSS_COEFFICIENT_KW_PER_C = 0.35

# F750 nominal COP at a typical Swedish winter operating point — a first
# guess, not measured for this installation (no delivered-heat sensor to
# calibrate against directly; see module docstring).
DEFAULT_ASSUMED_COP = 3.0


@dataclass(frozen=True)
class HourlySavingsRow:
    """One hour's contribution to the estimate.

    active: True iff this hour's actually-applied heat_offset_s1 register
        value was negative — i.e. the FIFTH LEVER's price-peak reduction was
        in effect (the only lever that ever asks for less heat than
        neutral). Inferred from the real applied register value (same
        source core/nibe/history.py already reads), not from a separate
        decision log, so a negative offset ever set by any other means would
        also count here — an accepted limitation, consistent with this
        package's general "reflect what was actually applied" philosophy.
    avoided_kwh: the modeled avoided energy this hour, or None if the hour
        wasn't active (nothing to estimate) or offset_c itself was
        unavailable.
    savings_kr: avoided_kwh valued at this hour's spot price, or None
        whenever avoided_kwh is None OR this hour's price wasn't available
        (a missing price does not zero out the kWh estimate — see
        estimate_reduction_savings' totals handling).
    """

    timestamp: str
    offset_c: float | None
    price_ore_per_kwh: float | None
    active: bool
    avoided_kwh: float | None
    savings_kr: float | None


@dataclass(frozen=True)
class SavingsEstimate:
    hours: list[HourlySavingsRow]
    total_avoided_kwh: float
    total_savings_kr: float
    active_hours: int
    heat_loss_coefficient_kw_per_c: float
    assumed_cop: float


def estimate_reduction_savings(
    hourly: list[tuple[str, float | None, float | None]],
    *,
    heat_loss_coefficient_kw_per_c: float = DEFAULT_HEAT_LOSS_COEFFICIENT_KW_PER_C,
    assumed_cop: float = DEFAULT_ASSUMED_COP,
) -> SavingsEstimate:
    """Estimate today's price-peak-reduction savings from a caller-assembled
    per-hour series.

    hourly: list of (timestamp, offset_c, price_ore_per_kwh) tuples, one per
        hour bucket, in any order (the caller — backend/nibe_api.py — owns
        aligning offset history with price history; this function does no
        date/time math itself, same convention as core/nibe/decision.py).
        offset_c is the actually-applied number.heat_offset_s1 value for
        that hour (None if unavailable that hour). price_ore_per_kwh is that
        hour's spot price in öre/kWh (None if unavailable).

    For each hour where offset_c < 0 (active):
        avoided_kwh = |offset_c| * heat_loss_coefficient_kw_per_c / assumed_cop
        savings_kr = avoided_kwh * price_ore_per_kwh / 100  (öre -> kr)

    total_avoided_kwh sums every active hour's avoided_kwh regardless of
    whether that hour's price was available (the kWh estimate doesn't need a
    price). total_savings_kr only sums hours where BOTH offset and price
    were available — a missing price for one hour understates the kr total
    slightly rather than fabricating a price, same "never guess a number
    that looks measured" stance as the rest of this codebase.
    """
    rows: list[HourlySavingsRow] = []
    total_kwh = 0.0
    total_kr = 0.0
    active_hours = 0

    for timestamp, offset_c, price_ore in hourly:
        active = offset_c is not None and offset_c < 0
        avoided_kwh: float | None = None
        savings_kr: float | None = None

        if active:
            avoided_kwh = abs(offset_c) * heat_loss_coefficient_kw_per_c / assumed_cop
            total_kwh += avoided_kwh
            active_hours += 1
            if price_ore is not None:
                savings_kr = avoided_kwh * price_ore / 100.0
                total_kr += savings_kr

        rows.append(
            HourlySavingsRow(
                timestamp=timestamp,
                offset_c=offset_c,
                price_ore_per_kwh=price_ore,
                active=active,
                avoided_kwh=avoided_kwh,
                savings_kr=savings_kr,
            )
        )

    return SavingsEstimate(
        hours=rows,
        total_avoided_kwh=total_kwh,
        total_savings_kr=total_kr,
        active_hours=active_hours,
        heat_loss_coefficient_kw_per_c=heat_loss_coefficient_kw_per_c,
        assumed_cop=assumed_cop,
    )
