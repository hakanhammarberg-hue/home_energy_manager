"""Unit tests for core.bess.battery_override — pure functions, no HA, no
mocking needed. Run with `pytest` from the repo root (same convention as
core/nibe/tests/test_decision.py and core/governor/tests/test_peak_governor.py).

This repo had zero test files under core/bess/ until this patch (Fas 6,
2026-10-09) — same situation core/governor/tests/test_peak_governor.py's own
docstring noted for core/governor/.
"""

import datetime

from core.bess.battery_override import (
    DEFAULT_ANTI_DORMANCY_IDLE_MINUTES,
    DEFAULT_ANTI_DORMANCY_PULSE_MINUTES,
    DEFAULT_ANTI_DORMANCY_SOC_THRESHOLD,
    decide_forced_charge,
    is_forced_charge_window_open,
)

NOW = datetime.datetime(2026, 10, 9, 22, 0, 0)


def _decide(**overrides):
    defaults = dict(
        now=NOW,
        soc_percent=10.0,
        max_soc_percent=100.0,
        override_until=None,
        anti_dormancy_enabled=False,
        last_nonzero_power_ts=None,
        pulse_until=None,
    )
    defaults.update(overrides)
    return decide_forced_charge(**defaults)


# ---------------------------------------------------------------------------
# Manual override
# ---------------------------------------------------------------------------


def test_override_active_within_window():
    d = _decide(override_until=NOW + datetime.timedelta(minutes=30))
    assert d.active
    assert d.reason == "manual_override"
    assert d.until == NOW + datetime.timedelta(minutes=30)
    assert not d.override_cleared


def test_override_clears_when_time_expired():
    d = _decide(override_until=NOW - datetime.timedelta(seconds=1))
    assert not d.active
    assert d.override_cleared


def test_override_clears_exactly_at_expiry():
    d = _decide(override_until=NOW)
    assert not d.active
    assert d.override_cleared


def test_override_clears_when_soc_cap_reached():
    d = _decide(
        override_until=NOW + datetime.timedelta(minutes=30),
        soc_percent=100.0,
        max_soc_percent=100.0,
    )
    assert not d.active
    assert d.override_cleared


def test_override_stays_active_when_soc_below_cap():
    d = _decide(
        override_until=NOW + datetime.timedelta(minutes=30),
        soc_percent=99.9,
        max_soc_percent=100.0,
    )
    assert d.active
    assert not d.override_cleared


def test_override_with_unknown_soc_does_not_clear_on_cap_grounds():
    # soc_percent=None can't prove the cap was reached — only the time
    # bound can clear it in that case.
    d = _decide(
        override_until=NOW + datetime.timedelta(minutes=30),
        soc_percent=None,
    )
    assert d.active
    assert not d.override_cleared


def test_override_takes_precedence_over_anti_dormancy_same_tick():
    d = _decide(
        override_until=NOW + datetime.timedelta(minutes=30),
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=2),
    )
    assert d.active
    assert d.reason == "manual_override"


# ---------------------------------------------------------------------------
# Anti-dormancy
# ---------------------------------------------------------------------------


def test_anti_dormancy_disabled_never_triggers():
    d = _decide(
        anti_dormancy_enabled=False,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=2),
    )
    assert not d.active
    assert d.reason == "none"


def test_anti_dormancy_soc_above_threshold_does_not_trigger():
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=DEFAULT_ANTI_DORMANCY_SOC_THRESHOLD + 0.1,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=2),
    )
    assert not d.active


def test_anti_dormancy_at_threshold_can_trigger():
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=DEFAULT_ANTI_DORMANCY_SOC_THRESHOLD,
        last_nonzero_power_ts=NOW
        - datetime.timedelta(minutes=DEFAULT_ANTI_DORMANCY_IDLE_MINUTES + 1),
    )
    assert d.active
    assert d.reason == "anti_dormancy"
    assert d.pulse_started


def test_anti_dormancy_not_idle_long_enough_does_not_trigger():
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW
        - datetime.timedelta(minutes=DEFAULT_ANTI_DORMANCY_IDLE_MINUTES - 1),
    )
    assert not d.active


def test_anti_dormancy_missing_idle_timestamp_does_not_trigger():
    # Burden of proof on triggering a new pulse — unknown idle history
    # never fires one, same convention as every other gate in this app.
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=None,
    )
    assert not d.active
    assert d.reason == "none"


def test_anti_dormancy_pulse_sets_until_from_now():
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=1),
    )
    assert d.pulse_started
    assert d.until == NOW + datetime.timedelta(
        minutes=DEFAULT_ANTI_DORMANCY_PULSE_MINUTES
    )


def test_anti_dormancy_existing_pulse_continues_without_restarting():
    pulse_until = NOW + datetime.timedelta(minutes=2)
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=1),
        pulse_until=pulse_until,
    )
    assert d.active
    assert d.reason == "anti_dormancy"
    assert d.until == pulse_until
    assert not d.pulse_started  # already running, not newly started


def test_anti_dormancy_pulse_ends_when_pulse_until_passed():
    d = _decide(
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(minutes=1),
        pulse_until=NOW - datetime.timedelta(seconds=1),
    )
    # pulse_until has passed and the battery has only been idle 1 minute
    # (well under the 30-minute threshold) — must not immediately re-fire.
    assert not d.active


def test_anti_dormancy_disabled_mid_pulse_still_completes_it():
    # A setting flip mid-pulse should not abruptly cut a charge pulse that
    # is already underway — see module docstring.
    pulse_until = NOW + datetime.timedelta(minutes=2)
    d = _decide(
        anti_dormancy_enabled=False,
        soc_percent=5.0,
        pulse_until=pulse_until,
    )
    assert d.active
    assert d.reason == "anti_dormancy"


def test_anti_dormancy_override_cleared_flag_propagates_alongside_pulse_start():
    d = _decide(
        override_until=NOW - datetime.timedelta(minutes=1),  # just expired
        anti_dormancy_enabled=True,
        soc_percent=5.0,
        last_nonzero_power_ts=NOW - datetime.timedelta(hours=1),
    )
    assert d.override_cleared
    assert d.active
    assert d.reason == "anti_dormancy"
    assert d.pulse_started


# ---------------------------------------------------------------------------
# is_forced_charge_window_open — the read-only check
# ---------------------------------------------------------------------------


def test_window_open_false_when_nothing_active():
    assert not is_forced_charge_window_open(
        now=NOW,
        soc_percent=50.0,
        max_soc_percent=100.0,
        override_until=None,
        pulse_until=None,
    )


def test_window_open_true_during_override():
    assert is_forced_charge_window_open(
        now=NOW,
        soc_percent=50.0,
        max_soc_percent=100.0,
        override_until=NOW + datetime.timedelta(minutes=10),
        pulse_until=None,
    )


def test_window_open_false_once_override_time_passed():
    assert not is_forced_charge_window_open(
        now=NOW,
        soc_percent=50.0,
        max_soc_percent=100.0,
        override_until=NOW - datetime.timedelta(seconds=1),
        pulse_until=None,
    )


def test_window_open_false_once_soc_cap_reached():
    assert not is_forced_charge_window_open(
        now=NOW,
        soc_percent=100.0,
        max_soc_percent=100.0,
        override_until=NOW + datetime.timedelta(minutes=10),
        pulse_until=None,
    )


def test_window_open_true_during_pulse():
    assert is_forced_charge_window_open(
        now=NOW,
        soc_percent=5.0,
        max_soc_percent=100.0,
        override_until=None,
        pulse_until=NOW + datetime.timedelta(minutes=2),
    )


def test_window_open_false_once_pulse_passed():
    assert not is_forced_charge_window_open(
        now=NOW,
        soc_percent=5.0,
        max_soc_percent=100.0,
        override_until=None,
        pulse_until=NOW - datetime.timedelta(seconds=1),
    )
