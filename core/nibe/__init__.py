"""core.nibe — comfort-lever control for the Nibe F750 heat pump.

STATUS: Fas 4a (2026-09-20, revised 2026-09-22) — decision.py and
controller.py exist and are provably inert (same "capability without a
caller" pattern core.zaptec used for its own Fas 3a): nothing in the app
calls either module automatically unless nibe.enabled is turned on in
Settings (default False — demo-first, per Håkan's explicit "Demo-run
först", 2026-09).

THIS SUPERSEDES THE PLAN PREVIOUSLY WRITTEN HERE — TWICE NOW
    Round 1 (pre-2026-09-20): an earlier version of this docstring
    (written before the LilyGO/ESPHome gateway was physically installed
    and before real entities existed to design against) planned to port
    nibe_price_control.py's curve-offset control (controller.py) and DHW
    pre-boost (dhw.py) verbatim into this package. That plan was
    abandoned once the gateway was live and 652 real entities were
    visible, specifically over an unconfirmed interaction risk: whether
    `switch.allow_heating_47371 = off` (a lever the old pyscript used)
    also suppresses the pump's defrost cycles — a real problem in a
    Swedish winter. SG Ready was adopted instead, reasoning that it
    signals a *preference* rather than disabling anything, so the pump's
    own firmware keeps owning defrost and safety logic.

    Round 2 (2026-09-22): live investigation against Håkan's actual F750
    found the SG Ready plan doesn't work on his hardware. The
    `switch.sg_ready_heating_*`/`switch.sg_ready_hot_water_*` entities are
    NOT actuators — they're per-function opt-in flags with zero effect
    unless the pump's real SG Ready condition (derived from TWO physical
    relay-driven inputs, `sensor.sg_ready_input_a_44878` +
    `_input_b_44879`, combined into `sensor.state_sg_ready_44874`) is
    something other than Normal. Håkan has no relay hardware wired to two
    AUX terminals — confirmed directly answering his own question: menu
    5.1 only lets you *assign* a function to a single AUX slot, and
    assigning SG Ready to just one AUX does nothing regardless of which
    AUX number is chosen, because the mechanism needs both, physically
    wired. Cross-checked against two Home Assistant Community threads:
    one using Shelly relays to drive exactly this two-input mechanism on
    an F-series pump, one describing a newer firmware's software-only
    alternative (`number.requested_operating_mode_sg_ready_*` + an
    "activate via API" switch) that a full entity-catalog search confirms
    does NOT exist on Håkan's F750.

    Given that, this module now targets `number.heat_offset_s1_47011`
    directly for the heating-boost lever — see decision.py's MECHANISM
    CHOICE section for the full reasoning, including why this does NOT
    reopen the original defrost concern (that was specific to Allow
    Heating, not curve-offset). This is, in effect, the Round 1 plan
    reinstated, now that the actual risk it was rejected over has been
    re-examined and found not to apply to curve-offset specifically.
    True two-relay SG Ready remains available later if Håkan ever wires
    physical AUX relays — tracked as a future option, not blocking
    anything here.

MODULE STRUCTURE (as actually built, 2026-09-20, mechanism revised 2026-09-22)
    decision.py   — pure decision logic, zero I/O, mirrors
        core.zaptec.scheduler's shape exactly:
            decide_heating_boost() — space-heating curve-offset comfort boost
            decide_dhw_luxury()    — the dashboard "Lyxläge varmvatten" toggle
    controller.py — NibeController, the read/write capability layer,
        mirrors core.zaptec.controller.ZaptecController's shape and safety
        story exactly (test_mode gated, wired to the same demo_mode flag as
        Growatt/Zaptec). Also documents the write-safety classification
        (everyday/guarded/blocked) this package commits to.

CONFIRMED REAL ENTITIES (Håkan's HA instance, LilyGO/ESPHome gateway live,
2026-09 conversation — 652 entities total under nibe_heatpump, area
"Tvättstuga"). Registry status as of 2026-09-22:
    number.heat_offset_s1_47011 — EVERYDAY tier, space-heating lever (was
        switch.sg_ready_heating_48282 before the 2026-09-22 pivot). Was
        disabled_by="integration" (Home Assistant's own default for most
        of this integration's ~650 registers, unrelated to any hardware
        problem); enabled + nibe_heatpump config entry reloaded 2026-09-22
        — confirmed live, reads "0.0", range -10..+10 step 1.
    select.hot_water_comfort_mode_47041 — GUARDED tier, Lyxläge's target.
        Same disabled_by="integration" story; enabled + reloaded
        2026-09-22 — confirmed live, options
        ["ECONOMY","NORMAL","LUXURY","SMART CONTROL"] (all uppercase —
        controller.py's DHW_COMFORT_MODE_* constants were originally
        wrong-case and have been corrected to match).
    switch.sg_ready_heating_48282, switch.sg_ready_hot_water_48284,
    switch.sg_ready_cooling_48283, switch.sg_ready_pool_48285 — exist,
        confirmed enabled+live 2026-09-22, but read "unavailable": no
        function responds to them without the two physical AUX inputs
        described above. No longer written by this package. Left exactly
        as the pump defaults them.
    sensor.sg_ready_input_a_44878, sensor.sg_ready_input_b_44879,
    sensor.state_sg_ready_44874 — the real physical SG Ready inputs/state.
        Exist in the registry but still disabled_by="integration" (not
        yet enabled — no reason to, since nothing in this package uses
        them without relay hardware Håkan doesn't have).
    sensor.smart_price_adaption_hw_comfort_mode_44897,
    sensor.state_smart_price_adaption_44908 — the pump's OWN built-in
        price-adaptation for hot water. Enabled + confirmed live
        2026-09-22: currently reads "ECO" / "10" respectively. These are
        READ-ONLY monitoring sensors — no switch entity exists via Modbus
        to enable/disable this native feature from Home Assistant, so it
        can only be turned off in the pump's own menu if Håkan wants this
        package's Lyxläge lever to be the sole thing steering
        select.hot_water_comfort_mode_47041. Worth checking the pump menu
        before relying on Lyxläge: if the native feature is actively
        overriding the same select entity, the two could visibly fight
        (one write from _poll_nibe, one from the pump itself, alternating).
    number.heat_curve_s1_47007 — exists, enabled+live 2026-09-22 alongside
        heat_offset_s1 above, not used by this package (offset, not curve
        shape, is the lever decision.py needs).

STILL BLOCKING FAS 4b GOING LIVE (tracked in the project status doc, not
silently assumed done here):
    - No watchdog/dead-man's-timer exists yet for these writes (see
      controller.py's docstring) — required before nibe.enabled runs with
      demo_mode off.
    - Whether Håkan wants to check/disable the pump's native "Smart Price
      Adaption" for hot water in its own menu before turning on
      nibe.dhw_luxury_enabled (see sensor entries above) — not yet
      confirmed either way.
    - No dedicated Settings tab for these entity IDs yet — same "Fas N
      stopgap: hardcoded constants in app.py" pattern core.perific/
      core.zaptec used before their own settings UI existed.
"""
