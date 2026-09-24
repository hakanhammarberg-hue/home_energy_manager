"""Unit tests for core.nibe.decision — pure functions, no HA, no mocking
needed. Run with `pytest` from the repo root (backend/ is on sys.path the
same way app.py's own `from core.governor import peak_governor` expects).
"""

from core.nibe.decision import (
    DEFAULT_HEAT_OFFSET_BOOST_C,
    decide_dhw_luxury,
    decide_heating_boost,
)

CHEAP_TODAY = [10.0, 20.0, 30.0, 40.0]  # median/threshold at p=0.5 -> 20.0


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
