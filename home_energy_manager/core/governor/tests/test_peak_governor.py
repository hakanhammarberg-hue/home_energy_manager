"""Unit tests for core.governor.peak_governor — pure functions, no HA, no
mocking needed. Run with `pytest` from the repo root (same convention as
core/nibe/tests/test_decision.py).

Covers decide() (the EV lever, pre-existing but previously untested — this
repo had zero test files under core/governor/ until this patch) and
decide_nibe_effektvakt() (the new Nibe lever, added 2026-10-06).
"""

from core.governor.peak_governor import (
    NIBE_EFFEKTVAKT_FLOOR_KW,
    NIBE_LEVER_DELAY_CYCLES,
    ZAPTEC_FLOOR_CURRENT,
    ZAPTEC_NORMAL_MAX_CURRENT,
    decide,
    decide_nibe_effektvakt,
)

# ---------------------------------------------------------------------------
# decide() — the EV lever
# ---------------------------------------------------------------------------


def test_decide_no_data_when_power_reading_missing():
    d = decide(current_kw=None, target_kw=12.0, ev_current_a=16, charging_switch_on=True)
    assert d.status == "no_data"
    assert d.ev_current_target_a is None
    assert not d.pause_charging
    assert not d.resume_charging


def test_decide_within_budget_restores_toward_normal_max():
    d = decide(current_kw=8.0, target_kw=12.0, ev_current_a=10, charging_switch_on=True)
    assert d.status == "within_budget"
    assert d.ev_current_target_a == 11  # RESTORE_STEP_A=1, capped at normal max 16


def test_decide_within_budget_resumes_paused_charging():
    d = decide(current_kw=8.0, target_kw=12.0, ev_current_a=16, charging_switch_on=False)
    assert d.status == "within_budget"
    assert d.resume_charging is True


def test_decide_over_budget_throttles_down():
    d = decide(current_kw=14.0, target_kw=12.0, ev_current_a=16, charging_switch_on=True)
    assert d.status == "throttling_ev"
    assert d.ev_current_target_a is not None
    assert d.ev_current_target_a < 16


def test_decide_over_budget_pauses_below_floor():
    # 16A down to a floor of 6A at CURRENT_STEP_A=2/cycle needs a huge
    # overshoot to jump straight past the floor in one cycle.
    d = decide(current_kw=40.0, target_kw=12.0, ev_current_a=7, charging_switch_on=True)
    assert d.status == "throttling_ev"
    assert d.pause_charging is True
    assert d.ev_current_target_a is None


def test_decide_over_budget_no_data_when_ev_current_unavailable():
    d = decide(current_kw=14.0, target_kw=12.0, ev_current_a=None, charging_switch_on=None)
    assert d.status == "no_data"
    assert "Zaptec current entity unavailable" in d.reason


def test_decide_respects_configurable_normal_max_current():
    d = decide(
        current_kw=8.0,
        target_kw=12.0,
        ev_current_a=18,
        charging_switch_on=True,
        normal_max_current=20,
    )
    assert d.ev_current_target_a == 19  # restores toward 20, not the module default 16


# ---------------------------------------------------------------------------
# decide_nibe_effektvakt() — the second, slower lever (added 2026-10-06)
# ---------------------------------------------------------------------------


def test_nibe_disabled_is_a_pure_noop():
    d = decide_nibe_effektvakt(
        enabled=False,
        over_budget_streak=99,
        effektvakt_current_kw=1.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=0.0,
    )
    assert d.status == "disabled"
    assert d.effektvakt_target_kw is None


def test_nibe_no_data_when_register_unavailable():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=5,
        effektvakt_current_kw=None,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=None,
    )
    assert d.status == "no_data"
    assert d.effektvakt_target_kw is None


def test_nibe_no_data_when_baseline_not_configured():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=5,
        effektvakt_current_kw=3.0,
        effektvakt_baseline_kw=None,
        seconds_since_last_nibe_contact=None,
    )
    assert d.status == "no_data"


def test_nibe_below_delay_threshold_does_nothing_when_already_at_baseline():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=0,
        effektvakt_current_kw=3.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
    )
    assert d.status == "within_budget"
    assert d.effektvakt_target_kw is None


def test_nibe_below_delay_threshold_restores_toward_baseline():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=0,
        effektvakt_current_kw=2.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
        step_up_kw=0.25,
    )
    assert d.status == "within_budget"
    assert d.effektvakt_target_kw == 2.25


def test_nibe_restore_clamps_to_baseline_not_past_it():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=0,
        effektvakt_current_kw=2.9,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
        step_up_kw=0.25,
    )
    assert d.effektvakt_target_kw == 3.0  # not 3.15


def test_nibe_streak_below_delay_cycles_still_does_nothing_extra():
    # delay_cycles default is 3 — a streak of 2 should NOT throttle yet.
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES - 1,
        effektvakt_current_kw=3.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
    )
    assert d.status == "within_budget"


def test_nibe_throttles_once_delay_cycles_reached():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES,
        effektvakt_current_kw=3.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
        step_down_kw=0.5,
    )
    assert d.status == "throttling_nibe"
    assert d.effektvakt_target_kw == 2.5


def test_nibe_throttle_clamps_to_floor_not_below_it():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES,
        effektvakt_current_kw=1.2,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
        floor_kw=1.0,
        step_down_kw=0.5,
    )
    assert d.effektvakt_target_kw == 1.0  # not 0.7


def test_nibe_throttle_at_floor_already_reports_engaged_with_no_further_write():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES,
        effektvakt_current_kw=1.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=10.0,
        floor_kw=1.0,
        step_down_kw=0.5,
    )
    assert d.status == "throttling_nibe"
    assert d.effektvakt_target_kw is None  # nothing left to lower, no redundant write
    assert "nothing more to give" in d.reason


def test_nibe_watchdog_forces_restore_when_stale_and_suppressed():
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES,  # would otherwise keep throttling
        effektvakt_current_kw=1.5,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=901.0,
        watchdog_timeout_s=900.0,
    )
    assert d.status == "watchdog_reset"
    assert d.effektvakt_target_kw == 3.0  # full jump back, not step-limited


def test_nibe_watchdog_does_not_fire_when_already_at_baseline():
    # Nothing stuck to force back — a stale read alone shouldn't manufacture
    # a status change when there's nothing suppressed.
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=0,
        effektvakt_current_kw=3.0,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=901.0,
        watchdog_timeout_s=900.0,
    )
    assert d.status == "within_budget"


def test_nibe_watchdog_does_not_fire_during_startup_grace():
    # seconds_since_last_nibe_contact=None means "no successful read yet
    # since process start" — must not be treated as a timeout.
    d = decide_nibe_effektvakt(
        enabled=True,
        over_budget_streak=NIBE_LEVER_DELAY_CYCLES,
        effektvakt_current_kw=1.5,
        effektvakt_baseline_kw=3.0,
        seconds_since_last_nibe_contact=None,
    )
    assert d.status == "throttling_nibe"


def test_nibe_constants_match_confirmed_values():
    # Pins the real, Håkan-confirmed values (2026-10-06) against silent
    # drift — not a behavior test, a "did someone change this without
    # noticing" tripwire.
    assert NIBE_LEVER_DELAY_CYCLES == 3
    assert NIBE_EFFEKTVAKT_FLOOR_KW == 1.0
    assert ZAPTEC_FLOOR_CURRENT == 6
    assert ZAPTEC_NORMAL_MAX_CURRENT == 16
