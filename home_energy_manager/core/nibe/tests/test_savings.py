"""Unit tests for core.nibe.savings — pure functions, no HA, no mocking
needed. Run with `pytest` from the repo root, same convention as
test_decision.py/test_history.py.
"""

from core.nibe.savings import (
    DEFAULT_ASSUMED_COP,
    DEFAULT_HEAT_LOSS_COEFFICIENT_KW_PER_C,
    estimate_reduction_savings,
)


def test_inactive_hours_contribute_nothing():
    hourly = [
        ("2026-09-28T01:00:00+00:00", 0.0, 50.0),
        ("2026-09-28T02:00:00+00:00", 2.0, 50.0),  # boost lever, not reduction
        ("2026-09-28T03:00:00+00:00", None, 50.0),  # offset unavailable
    ]
    estimate = estimate_reduction_savings(hourly)
    assert estimate.active_hours == 0
    assert estimate.total_avoided_kwh == 0.0
    assert estimate.total_savings_kr == 0.0
    assert all(not row.active for row in estimate.hours)
    assert all(row.avoided_kwh is None for row in estimate.hours)


def test_active_hour_computes_avoided_kwh_and_savings_kr():
    hourly = [("2026-09-28T18:00:00+00:00", -2.0, 150.0)]
    estimate = estimate_reduction_savings(hourly)

    expected_kwh = 2.0 * DEFAULT_HEAT_LOSS_COEFFICIENT_KW_PER_C / DEFAULT_ASSUMED_COP
    expected_kr = expected_kwh * 150.0 / 100.0

    assert estimate.active_hours == 1
    row = estimate.hours[0]
    assert row.active is True
    assert row.avoided_kwh == expected_kwh
    assert row.savings_kr == expected_kr
    assert estimate.total_avoided_kwh == expected_kwh
    assert estimate.total_savings_kr == expected_kr


def test_missing_price_still_counts_kwh_but_not_kr():
    hourly = [("2026-09-28T18:00:00+00:00", -2.0, None)]
    estimate = estimate_reduction_savings(hourly)

    assert estimate.active_hours == 1
    assert estimate.total_avoided_kwh > 0.0
    assert estimate.total_savings_kr == 0.0
    assert estimate.hours[0].savings_kr is None


def test_multiple_active_hours_sum_correctly():
    hourly = [
        ("2026-09-28T17:00:00+00:00", -2.0, 100.0),
        ("2026-09-28T18:00:00+00:00", -2.0, 200.0),
        ("2026-09-28T19:00:00+00:00", 0.0, 80.0),
    ]
    estimate = estimate_reduction_savings(hourly)

    per_hour_kwh = 2.0 * DEFAULT_HEAT_LOSS_COEFFICIENT_KW_PER_C / DEFAULT_ASSUMED_COP
    expected_kwh = per_hour_kwh * 2
    expected_kr = per_hour_kwh * 100.0 / 100.0 + per_hour_kwh * 200.0 / 100.0

    assert estimate.active_hours == 2
    assert estimate.total_avoided_kwh == expected_kwh
    assert abs(estimate.total_savings_kr - expected_kr) < 1e-9


def test_custom_constants_are_honored_and_returned():
    hourly = [("2026-09-28T18:00:00+00:00", -3.0, 100.0)]
    estimate = estimate_reduction_savings(
        hourly, heat_loss_coefficient_kw_per_c=0.5, assumed_cop=2.5
    )

    expected_kwh = 3.0 * 0.5 / 2.5
    assert estimate.total_avoided_kwh == expected_kwh
    assert estimate.heat_loss_coefficient_kw_per_c == 0.5
    assert estimate.assumed_cop == 2.5


def test_empty_input_returns_zeroed_estimate():
    estimate = estimate_reduction_savings([])
    assert estimate.hours == []
    assert estimate.total_avoided_kwh == 0.0
    assert estimate.total_savings_kr == 0.0
    assert estimate.active_hours == 0
