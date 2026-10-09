"""Unit tests for core.nibe.decision — pure functions, no HA, no mocking
needed. Run with `pytest` from the repo root (backend/ is on sys.path the
same way app.py's own `from core.governor import peak_governor` expects).
"""

from core.nibe.decision import (
    DEFAULT_DEGREE_MINUTES_FLOOR,
    DEFAULT_EXPENSIVE_PRICE_PERCENTILE,
    DEFAULT_HEAT_OFFSET_BOOST_C,
    DEFAULT_HEAT_OFFSET_REDUCTION_C,
    DEFAULT_MAX_CONTINUOUS_ECONOMY_S,
    DEFAULT_MAX_INDOOR_TEMP_C,
    DEFAULT_PRICE_SPIKE_MIN_DELTA_ORE,
    DEFAULT_PRICE_SPIKE_PERCENTILE,
    DEFAULT_UPGRADE_COOLDOWN_S,
    DEFAULT_WATCHDOG_TIMEOUT_S,
    decide_dhw_luxury,
    decide_heating_boost,
)

CHEAP_TODAY = [10.0, 20.0, 30.0, 40.0]  # median/threshold at p=0.5 -> 20.0

# A flat-ish "known prices" reference series where the 85th percentile
# (DEFAULT_PRICE_SPIKE_PERCENTILE) lands at 90.0 — used by the price-spike
# tests below. 20 values so nearest-rank percentile math lands cleanly.
KNOWN_PRICES_WITH_SPIKE = [20.0 + i * 5.0 for i in range(20)]  # 20.0..115.0
SPIKE_THRESHOLD = sorted(KNOWN_PRICES_WITH_SPIKE)[
    round(DEFAULT_PRICE_SPIKE_PERCENTILE * (len(KNOWN_PRICES_WITH_SPIKE) - 1))
]


# ---------------------------------------------------------------------------
# decide_heating_boost
# ---------------------------------------------------------------------------


def test_heating_boost_engages_on_cheap_price():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_heating_boost_engages_on_solar_surplus():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=100.0,  # expensive — would not engage on price alone
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=1.5,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "engaged_solar_surplus"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_heating_boost_normal_when_neither_condition_holds():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=0.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_heating_boost_missing_price_and_solar_stays_normal_not_no_data():
    """Burden of proof is on the exception (mirrors core.zaptec.scheduler's
    above-cap logic) — missing exception data doesn't stall the decision,
    it just fails to prove the exception."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=None,
        today_prices_ore_per_kwh=None,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_heating_boost_blocked_when_governor_has_no_headroom():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,  # would otherwise engage
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
    )
    assert d.status == "no_headroom"
    assert d.heat_offset_c == 0


def test_heating_boost_allowed_when_governor_has_headroom():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=5.0,
        target_kw=12.0,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_heating_boost_no_data_when_governor_enabled_but_power_unknown():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=None,
        target_kw=12.0,
    )
    assert d.status == "no_data"
    assert d.heat_offset_c is None


def test_heating_boost_offset_never_exceeds_configured_max():
    """Even a caller-supplied heat_offset_boost_c well above the safety
    ceiling is decision.py's business to accept (controller.py clamps as
    the actual defense) — but the *default* must stay at the documented,
    conservative value so nothing upstream has to know the ceiling exists
    to get a safe result."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.heat_offset_c == 2


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4c predictive pre-heat (price_spike_boost_enabled)
# ---------------------------------------------------------------------------


def test_price_spike_ignored_when_feature_disabled():
    """price_spike_boost_enabled defaults to False — a huge upcoming spike
    must not engage anything until the flag is explicitly turned on,
    same nested-opt-in-flag contract as dhw_luxury_enabled."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=35.0,  # above CHEAP_TODAY's own cheap threshold (30.0)
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        upcoming_prices_ore_per_kwh=[SPIKE_THRESHOLD + 50.0],
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
        # price_spike_boost_enabled left at its False default
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_spike_engages_when_enabled_and_spike_is_real():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=35.0,  # above CHEAP_TODAY's own cheap threshold (30.0)
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=[30.0, 40.0, SPIKE_THRESHOLD + 20.0, 35.0],
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
    )
    assert d.status == "engaged_price_spike_ahead"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_price_spike_does_not_override_an_already_engaged_cheap_price():
    """Solar/cheap-price are checked first — a spike later today must never
    change the reported reason for a boost that's already justified."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,  # cheap by CHEAP_TODAY's own threshold
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=[SPIKE_THRESHOLD + 50.0],
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
    )
    assert d.status == "engaged_cheap_price"


def test_price_spike_requires_top_percentile_not_just_pricier_than_now():
    """A mildly higher upcoming price that never reaches the spike
    percentile must not engage — this lever is for genuine spikes, not any
    upward trend."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=35.0,  # above CHEAP_TODAY's own cheap threshold (30.0)
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=[40.0, 45.0],  # pricier, but nowhere near top 15%
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_spike_requires_minimum_delta_over_current_price():
    """Even a genuine top-percentile spike shouldn't trigger a boost if
    it's barely above the current price — DEFAULT_PRICE_SPIKE_MIN_DELTA_ORE
    guards against spending energy pre-heating for a negligible swing."""
    near_current = SPIKE_THRESHOLD + 1.0
    d = decide_heating_boost(
        spot_price_ore_per_kwh=near_current - (DEFAULT_PRICE_SPIKE_MIN_DELTA_ORE / 2),
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=[near_current],
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_spike_skipped_gracefully_when_no_forward_price_data():
    """Missing upcoming_prices_ore_per_kwh (e.g. Nordpool tomorrow prices
    not published yet) must not be an error — the exact lesson from this
    session's influxdb_7d_avg incident: a missing optional input degrades
    to 'not proven this cycle', never a fatal failure."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=35.0,  # above CHEAP_TODAY's own cheap threshold (30.0)
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=None,
        all_known_prices_ore_per_kwh=KNOWN_PRICES_WITH_SPIKE,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_spike_falls_back_to_upcoming_window_as_its_own_reference():
    """all_known_prices_ore_per_kwh is optional — when omitted, the
    upcoming window itself becomes the percentile reference set rather than
    failing or skipping the check entirely."""
    # spot sits at today's own most-expensive quarter, so the existing
    # cheap-price check can't itself explain a boost — isolates the
    # fallback behavior of the price-spike check specifically.
    today_with_spot_at_the_top = [100.0, 150.0, 200.0, 250.0]
    d = decide_heating_boost(
        spot_price_ore_per_kwh=250.0,
        today_prices_ore_per_kwh=today_with_spot_at_the_top,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_spike_boost_enabled=True,
        upcoming_prices_ore_per_kwh=[210.0, 210.0, 500.0],
        all_known_prices_ore_per_kwh=None,
    )
    assert d.status == "engaged_price_spike_ahead"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4d degree-minutes floor
# ---------------------------------------------------------------------------


def test_degree_minutes_floor_blocks_an_otherwise_engaged_cheap_price_boost():
    """The floor is a gate, not an exception — it must be able to suppress
    a boost that every other check would otherwise have approved."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,  # cheap by CHEAP_TODAY's own threshold
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 1,  # past the floor
    )
    assert d.status == "blocked_low_degree_minutes"
    assert d.heat_offset_c == 0


def test_degree_minutes_floor_blocks_solar_surplus_boost_too():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,  # would otherwise engage
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 50,
    )
    assert d.status == "blocked_low_degree_minutes"
    assert d.heat_offset_c == 0


def test_degree_minutes_at_exactly_the_floor_is_blocked():
    """<= floor blocks, matching the watchdog's own >= convention for 'at
    the boundary counts as triggered, not as still-safe'."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR,
    )
    assert d.status == "blocked_low_degree_minutes"


def test_degree_minutes_above_the_floor_does_not_block():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR + 1,  # just shy of the floor
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_degree_minutes_missing_does_not_block():
    """None (entity unavailable, HA unreachable, etc.) is not evidence the
    compressor is under load — same burden-of-proof convention as every
    other input in this module, applied to a gate instead of an exception."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=None,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_degree_minutes_floor_checked_before_solar_and_price_but_after_headroom():
    """Priority order: no_headroom still wins over the DM floor when the
    governor itself has zero headroom — the floor only matters once
    headroom is settled."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 100,  # also past the floor
    )
    assert d.status == "no_headroom"
    assert d.heat_offset_c == 0


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4f indoor-temperature ceiling
# ---------------------------------------------------------------------------


def test_indoor_temp_ceiling_blocks_an_otherwise_engaged_cheap_price_boost():
    """The ceiling is a gate, not an exception — same contract as the
    degree-minutes floor, mirrored test-for-test."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=DEFAULT_MAX_INDOOR_TEMP_C + 0.1,  # past the ceiling
    )
    assert d.status == "blocked_high_indoor_temp"
    assert d.heat_offset_c == 0


def test_indoor_temp_ceiling_blocks_solar_surplus_boost_too():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,  # would otherwise engage
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=30.0,
    )
    assert d.status == "blocked_high_indoor_temp"
    assert d.heat_offset_c == 0


def test_indoor_temp_at_exactly_the_ceiling_is_blocked():
    """>= ceiling blocks, matching the degree-minutes floor's own <=
    convention for 'at the boundary counts as triggered'."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=DEFAULT_MAX_INDOOR_TEMP_C,
    )
    assert d.status == "blocked_high_indoor_temp"


def test_indoor_temp_below_the_ceiling_does_not_block():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=DEFAULT_MAX_INDOOR_TEMP_C - 0.1,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_indoor_temp_missing_does_not_block():
    """None is not evidence the house is too warm — same burden-of-proof
    convention as every other input in this module."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=None,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_indoor_temp_ceiling_does_not_block_price_reduction():
    """A negative offset only reduces compressor demand — the ceiling has
    no reason to prevent that, mirroring the degree-minutes floor's own
    test_price_reduction_is_not_blocked_by_the_degree_minutes_floor."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=EXPENSIVE_THRESHOLD,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=30.0,
        price_reduction_enabled=True,
    )
    assert d.status == "reduced_expensive_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_REDUCTION_C


def test_indoor_temp_ceiling_checked_before_solar_and_price_but_after_headroom():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
        indoor_temp_c=30.0,  # also past the ceiling
    )
    assert d.status == "no_headroom"
    assert d.heat_offset_c == 0


def test_indoor_temp_ceiling_and_degree_minutes_floor_both_active_reports_indoor_temp():
    """When both gates would block, the indoor-temperature reason wins —
    see the module docstring's EIGHTH LEVER section."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 1,
        indoor_temp_c=30.0,
    )
    assert d.status == "blocked_high_indoor_temp"
    assert d.heat_offset_c == 0


def test_anti_flap_never_suppresses_the_indoor_temp_ceiling():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        indoor_temp_c=30.0,
        previous_heat_offset_c=DEFAULT_HEAT_OFFSET_BOOST_C,
        seconds_since_offset_last_changed=1.0,  # well within cooldown
        upgrade_cooldown_s=DEFAULT_UPGRADE_COOLDOWN_S,
    )
    assert d.status == "blocked_high_indoor_temp"
    assert d.heat_offset_c == 0


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4e active price-peak reduction (price_reduction_enabled)
# ---------------------------------------------------------------------------

# CHEAP_TODAY's own 85th-percentile (nearest-rank) threshold — the top value
# itself, since len(CHEAP_TODAY) == 4.
EXPENSIVE_THRESHOLD = sorted(CHEAP_TODAY)[
    round(DEFAULT_EXPENSIVE_PRICE_PERCENTILE * (len(CHEAP_TODAY) - 1))
]


def test_price_reduction_ignored_when_feature_disabled():
    """price_reduction_enabled defaults to False — an expensive price alone
    must not reduce the offset until the flag is explicitly turned on."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=EXPENSIVE_THRESHOLD,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        # price_reduction_enabled left at its False default
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_reduction_engages_on_expensive_price_when_enabled():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=EXPENSIVE_THRESHOLD,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
    )
    assert d.status == "reduced_expensive_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_REDUCTION_C


def test_price_reduction_skipped_when_price_not_in_expensive_tier():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=35.0,  # above cheap threshold, below EXPENSIVE_THRESHOLD (40.0)
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_price_reduction_never_overrides_an_already_engaged_boost():
    """A boost branch always wins if it fires — by construction the same
    price can't be both cheap and expensive, but solar surplus and an
    expensive price CAN coexist, and solar must still take priority."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=EXPENSIVE_THRESHOLD,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,  # would otherwise engage
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
    )
    assert d.status == "engaged_solar_surplus"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_price_reduction_is_not_blocked_by_the_degree_minutes_floor():
    """The DM floor only protects against asking for MORE heat — a negative
    offset reduces compressor demand, so it must fire even when degree_minutes
    is already past the floor (see module docstring's FIFTH LEVER section)."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=EXPENSIVE_THRESHOLD,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 100,  # deep past the floor
    )
    assert d.status == "reduced_expensive_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_REDUCTION_C


def test_degree_minutes_floor_still_blocks_when_reduction_does_not_apply():
    """When price_reduction_enabled is on but the price ISN'T expensive, the
    DM floor must still block a boost exactly as it did before this lever
    existed — Fas 4d's own behavior must be unaffected."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,  # cheap by CHEAP_TODAY's own threshold
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 1,
    )
    assert d.status == "blocked_low_degree_minutes"
    assert d.heat_offset_c == 0


def test_price_reduction_missing_price_data_does_not_block():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=None,
        today_prices_ore_per_kwh=None,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        price_reduction_enabled=True,
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4e anti-flap / upgrade hysteresis
# ---------------------------------------------------------------------------


def test_anti_flap_suppresses_an_upgrade_within_the_cooldown():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,  # would otherwise engage cheap-price boost
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        previous_heat_offset_c=0,
        seconds_since_offset_last_changed=DEFAULT_UPGRADE_COOLDOWN_S - 1,
    )
    assert d.status == "suppressed_anti_flap"
    assert d.heat_offset_c == 0  # held at the previous value


def test_anti_flap_allows_the_upgrade_once_cooldown_has_elapsed():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        previous_heat_offset_c=0,
        seconds_since_offset_last_changed=DEFAULT_UPGRADE_COOLDOWN_S,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_anti_flap_never_suppresses_a_downgrade():
    """A downgrade (here: falling back to neutral from a previous boost)
    must apply instantly, mirroring tengmo-ab's own 'instant downgrade'
    half of the pattern — no cooldown on the way down."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=100.0,  # no boost condition holds anymore
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        previous_heat_offset_c=DEFAULT_HEAT_OFFSET_BOOST_C,
        seconds_since_offset_last_changed=1.0,  # just changed a moment ago
    )
    assert d.status == "normal"
    assert d.heat_offset_c == 0


def test_anti_flap_does_not_apply_without_previous_state():
    """A fresh add-on start (no previous offset/timestamp tracked yet) must
    never be treated as 'just changed a moment ago' — same burden-of-proof
    convention as every other input in this module."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        previous_heat_offset_c=None,
        seconds_since_offset_last_changed=None,
    )
    assert d.status == "engaged_cheap_price"
    assert d.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C


def test_anti_flap_never_suppresses_the_degree_minutes_floor():
    """The DM floor is a hard safety status, never wrapped in anti-flap
    (see module docstring's SIXTH section) — even though moving from a
    previous -2 reduction up to 0 looks like an 'upgrade', the floor must
    take effect immediately, not be held off by a cooldown."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        degree_minutes=DEFAULT_DEGREE_MINUTES_FLOOR - 1,
        previous_heat_offset_c=DEFAULT_HEAT_OFFSET_REDUCTION_C,  # -2
        seconds_since_offset_last_changed=1.0,  # well within cooldown
    )
    assert d.status == "blocked_low_degree_minutes"
    assert d.heat_offset_c == 0


def test_anti_flap_never_suppresses_no_headroom():
    """Same as above but for the no_headroom hard status — the governor's
    fuse budget must never be held off by an anti-flap cooldown either."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
        previous_heat_offset_c=DEFAULT_HEAT_OFFSET_REDUCTION_C,  # -2
        seconds_since_offset_last_changed=1.0,
    )
    assert d.status == "no_headroom"
    assert d.heat_offset_c == 0


# ---------------------------------------------------------------------------
# decide_heating_boost — Fas 4b watchdog (seconds_since_last_nibe_contact)
# ---------------------------------------------------------------------------


def test_watchdog_not_triggered_under_threshold():
    """Just under the timeout, with headroom still unprovable: stays
    no_data, register untouched — same as if no watchdog existed at all."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=None,
        target_kw=12.0,
        seconds_since_last_nibe_contact=DEFAULT_WATCHDOG_TIMEOUT_S - 1,
    )
    assert d.status == "no_data"
    assert d.heat_offset_c is None


def test_watchdog_none_contact_behaves_like_fresh_contact():
    """No confirmed contact yet since startup (None) must NOT be treated as
    an infinitely-stale timeout — it's the normal state for the first tick
    or two after this add-on starts, and must not falsely trigger the
    watchdog before the pump has even been reached once."""
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=None,
        target_kw=12.0,
        seconds_since_last_nibe_contact=None,
    )
    assert d.status == "no_data"
    assert d.heat_offset_c is None


def test_watchdog_triggers_at_exactly_the_timeout():
    d = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=None,
        target_kw=12.0,
        seconds_since_last_nibe_contact=DEFAULT_WATCHDOG_TIMEOUT_S,
    )
    assert d.status == "watchdog_reset"
    assert d.heat_offset_c == 0


def test_watchdog_does_not_affect_cycles_with_known_headroom():
    """A huge seconds_since_last_nibe_contact must not matter at all once
    headroom is actually provable (True or False) — the watchdog only
    exists to cover the headroom-UNKNOWN branch, not to second-guess a
    cycle that already has a real answer."""
    huge_gap = DEFAULT_WATCHDOG_TIMEOUT_S * 100

    d_has_headroom = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=5.0,
        target_kw=12.0,
        seconds_since_last_nibe_contact=huge_gap,
    )
    assert d_has_headroom.status == "engaged_cheap_price"
    assert d_has_headroom.heat_offset_c == DEFAULT_HEAT_OFFSET_BOOST_C

    d_no_headroom = decide_heating_boost(
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,
        seconds_since_last_nibe_contact=huge_gap,
    )
    assert d_no_headroom.status == "no_headroom"
    assert d_no_headroom.heat_offset_c == 0


# ---------------------------------------------------------------------------
# decide_dhw_luxury
# ---------------------------------------------------------------------------


def test_dhw_luxury_disabled_is_a_pure_noop():
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "disabled"
    assert d.comfort_mode is None


def test_dhw_luxury_disabled_is_still_a_noop_when_current_mode_is_normal():
    # Disabled + a manual Normal/Smart Control choice on the pump's own
    # panel must stay completely untouched — only a stray Luxury or Economy
    # (this lever's own two possible residues) should ever trigger a reset.
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode="NORMAL",
    )
    assert d.status == "disabled"
    assert d.comfort_mode is None


def test_dhw_luxury_disabled_resets_a_stuck_economy_register_to_normal():
    # Real incident, 2026-10-09: Lyxläge was enabled with no cheap-price or
    # solar-surplus exception active, so economy_no_condition landed it on
    # Economy (~45°C hot water) within 20 minutes — then disabled a few
    # hours later, leaving it stuck there because the 2026-10-07 fix only
    # recognised a stray LUXURY as this lever's own residue.
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode="ECONOMY",
    )
    assert d.status == "disabled_reset_from_economy"
    assert d.comfort_mode == "normal"


def test_dhw_luxury_disabled_economy_reset_check_is_case_insensitive():
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=None,
        today_prices_ore_per_kwh=None,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode="economy",
    )
    assert d.status == "disabled_reset_from_economy"
    assert d.comfort_mode == "normal"


def test_dhw_luxury_disabled_resets_a_stuck_luxury_register_to_normal():
    # Bug found 2026-10-07: the toggle had been on, pushed Luxury, then was
    # switched off the same day — but nothing ever pulled the register back
    # down, so it stayed stuck on Luxury (58-64°C target band) for two days.
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=5.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode="LUXURY",
    )
    assert d.status == "disabled_reset_from_luxury"
    assert d.comfort_mode == "normal"


def test_dhw_luxury_disabled_reset_check_is_case_insensitive():
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=None,
        today_prices_ore_per_kwh=None,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode="luxury",
    )
    assert d.status == "disabled_reset_from_luxury"
    assert d.comfort_mode == "normal"


def test_dhw_luxury_disabled_is_a_noop_when_current_mode_unknown():
    # Unavailable/None must fail closed to "don't touch", not to "reset" —
    # resetting without proof the register is actually stuck on Luxury
    # would itself be an unwanted write.
    d = decide_dhw_luxury(
        enabled=False,
        spot_price_ore_per_kwh=None,
        today_prices_ore_per_kwh=None,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        current_comfort_mode=None,
    )
    assert d.status == "disabled"
    assert d.comfort_mode is None


def test_dhw_luxury_on_cheap_price():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "luxury_cheap_price"
    assert d.comfort_mode == "luxury"


def test_dhw_luxury_on_solar_surplus():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=2.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "luxury_solar_surplus"
    assert d.comfort_mode == "luxury"


def test_dhw_luxury_falls_back_to_economy_not_normal():
    """The resolved open question: fallback is Economy, matching Håkan's
    'cost savings is always priority one' rule — never Normal."""
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=0.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
    )
    assert d.status == "economy_no_condition"
    assert d.comfort_mode == "economy"


def test_dhw_luxury_blocked_by_governor_headroom_even_if_price_is_cheap():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,  # would otherwise be luxury
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
    )
    assert d.status == "no_headroom"
    assert d.comfort_mode == "economy"


def test_dhw_luxury_missing_headroom_data_fails_closed_to_economy():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=None,
        target_kw=12.0,
    )
    assert d.status == "no_headroom"
    assert d.comfort_mode == "economy"


def test_dhw_luxury_allowed_when_governor_has_headroom():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=5.0,
        target_kw=12.0,
    )
    assert d.status == "luxury_cheap_price"
    assert d.comfort_mode == "luxury"


# ---------------------------------------------------------------------------
# decide_dhw_luxury — Fas 4e legionella/disinfection guard
# ---------------------------------------------------------------------------


def test_legionella_guard_forces_normal_after_max_continuous_economy():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=100.0,  # no luxury condition holds
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=0.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        seconds_since_last_non_economy=DEFAULT_MAX_CONTINUOUS_ECONOMY_S,
    )
    assert d.status == "forced_normal_legionella_guard"
    assert d.comfort_mode == "normal"


def test_legionella_guard_not_yet_triggered_under_the_limit():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=0.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        seconds_since_last_non_economy=DEFAULT_MAX_CONTINUOUS_ECONOMY_S - 1,
    )
    assert d.status == "economy_no_condition"
    assert d.comfort_mode == "economy"


def test_legionella_guard_missing_duration_does_not_trigger():
    """No tracked duration yet (fresh start, or a caller that hasn't wired
    the state tracking) must not be treated as a long Economy stretch —
    same burden-of-proof convention as everywhere else in this module."""
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=100.0,
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=0.0,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        seconds_since_last_non_economy=None,
    )
    assert d.status == "economy_no_condition"
    assert d.comfort_mode == "economy"


def test_legionella_guard_overrides_no_headroom_too():
    """Unlike every other check in this module, the legionella guard
    deliberately overrides the peak governor's own headroom check — see
    module docstring's SEVENTH section for why."""
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,  # would be luxury if headroom allowed it
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=True,
        current_kw=12.0,
        target_kw=12.0,  # zero headroom
        seconds_since_last_non_economy=DEFAULT_MAX_CONTINUOUS_ECONOMY_S,
    )
    assert d.status == "forced_normal_legionella_guard"
    assert d.comfort_mode == "normal"


def test_legionella_guard_does_not_affect_a_luxury_outcome():
    d = decide_dhw_luxury(
        enabled=True,
        spot_price_ore_per_kwh=10.0,  # cheap — luxury applies
        today_prices_ore_per_kwh=CHEAP_TODAY,
        solar_surplus_kw=None,
        governor_enabled=False,
        current_kw=None,
        target_kw=None,
        seconds_since_last_non_economy=DEFAULT_MAX_CONTINUOUS_ECONOMY_S * 10,
    )
    assert d.status == "luxury_cheap_price"
    assert d.comfort_mode == "luxury"
