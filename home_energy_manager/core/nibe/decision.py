"""core.nibe.decision — pure decision logic for the Nibe F750's two comfort
levers: space-heating curve-offset boost and DHW ("Lyxläge varmvatten")
luxury mode.

STATUS: Fas 4a (2026-09-20, revised 2026-09-22), Fas 4c predictive pre-heat
added 2026-09-25 (see THIRD LEVER section below), Fas 4d degree-minutes
floor added 2026-09-26 (see FOURTH LEVER section below). Fas 4e
(2026-09-26) added three more items from that day's GitHub/HA-Community
competitive scan (see claude/omvarldsbevakning-nibe-github-2026-09-26.md),
picked by Håkan as items 1-3 of that report's recommendation list: active
price-peak reduction (FIFTH LEVER), upgrade hysteresis/anti-flap (SIXTH
section), and a legionella/disinfection guard on DHW Economy (SEVENTH
section) — see each section below. Fas 4f (2026-10-09) added an indoor-
temperature ceiling (EIGHTH LEVER below), after a two-day operations
review found the boost lever had been engaged almost continuously and had
overheated the house. Mirrors core.zaptec.scheduler's shape exactly: pure
functions, no HA, no NibeController calls, testable without a live pump.

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

THIRD LEVER — PREDICTIVE PRE-HEAT (Fas 4c, 2026-09-25)
    Håkan's own framing (2026-09-25): today's boost is entirely reactive —
    it only fires once the current price is already cheap or the sun is
    already out. It says nothing about a forecastable expensive period
    coming up later (classically the evening peak), even though the whole
    point of a curve-offset boost is to bank heat in the building's/
    buffer's own thermal mass ahead of exactly that kind of window. This
    weekend's ER57-CU 200 addition (see
    claude/er57-buffer-plumbing-shopping-list.md) makes that banked heat
    meaningfully bigger (~235L combined vs. the old 35L internal buffer
    alone), which is what makes pre-heating worth adding now rather than
    later.

    decide_heating_boost() gained a third, independent exception —
    "engaged_price_spike_ahead" — checked after the existing solar-surplus
    and cheap-price checks (so it never overrides either; it only fires
    when neither of those already justified a boost). It compares the
    current price against the highest price in a forward-looking window
    (upcoming_prices_ore_per_kwh, assembled by the caller from today's
    remaining quarter-hours plus tomorrow's once Nordpool publishes them —
    see backend/app.py's _poll_nibe) rather than only today's static
    cheap-price percentile. Two conditions both have to hold, not just
    one, before this pre-heats:
        1. the upcoming peak is itself a genuine spike — at or above
           price_spike_percentile of all currently-known prices (today +
           tomorrow when available), not merely "pricier than now" (a
           mild rising trend shouldn't trigger a boost, exactly the same
           reasoning core.zaptec.scheduler uses percentile-of-known-prices
           rather than a fixed öre threshold elsewhere in this project);
        2. that peak is at least price_spike_min_delta_ore above the
           current price — guards against boosting for a spike that's
           technically in the top percentile but only marginally pricier
           than right now, where spending energy to pre-heat wouldn't be
           worth it.
    Gated by its own nibe.price_spike_boost_enabled flag
    (price_spike_boost_enabled param here), independent of
    dhw_luxury_enabled and of nibe.enabled itself being on — same nested
    opt-in-flag shape as dhw_luxury_enabled, so wiring this in changes
    nothing for anyone until it's explicitly turned on. Missing forward
    price data (upcoming_prices_ore_per_kwh empty/None — e.g. Nordpool
    tomorrow prices not published yet, ordinarily true until early
    afternoon) is NOT an error: the branch is simply skipped that cycle,
    same "burden of proof on the exception" contract as every other check
    in this module — a lesson taken directly from this same session's
    core.bess.battery_system_manager incident, where a missing-data case
    for a different feature (influxdb_7d_avg consumption forecasting) had
    no graceful fallback and fatally aborted an entire schedule computation
    instead of just skipping the one enhancement that needed the missing
    data.

    Reuses heat_offset_boost_c (the same +2 lever, same
    MAX_SAFE_HEAT_OFFSET_C ceiling in controller.py) rather than a second,
    larger constant — this is still the same conservative curve-offset
    register, and a season of real (demo_mode=False) data is what should
    justify going further, not a guess made before the ER57 buffer is even
    plumbed in.

    Prior art consulted (2026-09-25): github.com/Samot89/
    Smart-NIBE-Control-a-Home-Assistant-MQTT, a NIBE Modbus curve-offset
    blueprint independently built around the same "pre-heat 1-8h before a
    price rise" idea (their write-up calls it exactly that), among several
    other weighted factors (indoor-temperature correction, solar braking,
    a degree-minutes protection threshold, weather-forecast bonus). Their
    approach computes one continuously-blended offset from many signals
    at once; this module deliberately keeps the existing discrete-branch
    shape (solar OR cheap-price OR spike OR normal, each an all-or-nothing
    +2/0) instead of adopting a weighted-sum model — consistent with this
    whole package's "small, auditable, testable-without-a-live-pump"
    design goal, and because Håkan's own ask was specifically to add
    forward-looking price awareness, not to redesign the lever's shape.
    Their degree-minutes protection threshold (dm_threshold, guarding
    against compressor stress/bivalence activation) was flagged here as a
    genuinely useful idea not yet implemented — see FOURTH LEVER below for
    where it landed once a live degree-minutes entity was actually found
    and confirmed (2026-09-26).

FOURTH LEVER — DEGREE-MINUTES FLOOR, A GATE NOT AN EXCEPTION (Fas 4d, 2026-09-26)
    number.degree_minutes_16_bit_43005 ("Degree Minutes (16 bit)") was
    found disabled_by="integration" like almost everything else on this
    device, enabled + the nibe_heatpump config entry reloaded, and
    confirmed live (reading -40.0 DM at the time). A sibling
    number.degree_minutes_32_bit_40940 exists in the registry too but
    stays "unavailable" after the same enable+reload — same failure mode
    as the SG Ready AUX sensors and the GP1 operational-mode select
    elsewhere in this device: registered, but this F750 doesn't answer it
    over Modbus. The 16-bit register is the one this module reads.

    Degree-minutes is the pump's own running heat-deficit accumulator:
    at/near zero means no unmet demand, and it goes more negative the
    longer/harder the compressor needs to run to keep up. Nibe's own
    firmware uses a (installer-configurable, menu 5.1.x) DM threshold to
    decide when to bring in electric immersion/bivalent heat on top of the
    compressor — exactly the expensive fallback a cost-saving boost must
    not accidentally trigger. Unlike the other three levers above, this
    is NOT a new way to justify a boost — it's a ceiling check that can
    only ever suppress one: decide_heating_boost() now checks it right
    after governor headroom and before any of the three exception
    branches (solar / cheap-price / price-spike), so a deeply negative DM
    reading blocks the boost regardless of which of those three would
    otherwise have engaged it.

    Because this can only make the system MORE conservative, never less,
    it deliberately does NOT get its own nibe.*_enabled opt-in flag the
    way dhw_luxury_enabled and price_spike_boost_enabled do — it's live
    as soon as nibe.enabled itself is on, same as the pre-existing
    governor-headroom check. Gating a safety floor behind a separate
    "turn the safety on" switch would invert the whole point of it.

    degree_minutes_floor defaults to DEFAULT_DEGREE_MINUTES_FLOOR — an
    explicitly conservative first guess (Håkan, 2026-09-26: "Vi kan väl
    börja med ett konservativt värde"), not a measured value. Håkan's own
    installer menu setting for when electric addition actually kicks in
    is unknown; -400 DM sits in the same range the Smart-NIBE-Control
    project uses for the identical purpose (see THIRD LEVER above), with
    comfortable margin above the live -40 DM baseline this was written
    against. Revisit once a season of logged DM history (now that the
    entity is enabled — recorder starts from 2026-09-26) shows what this
    installation's real electric-addition threshold and normal winter
    range actually are.

    Missing degree_minutes (None — entity unavailable, HA unreachable,
    etc.) is NOT treated as a reason to block: same "burden of proof on
    the exception" convention this whole module already uses for
    price/solar data, applied here to a gate instead of an exception —
    absence of evidence that DM is dangerously low is not evidence that
    it is. This intentionally does NOT extend to decide_dhw_luxury() yet;
    Håkan's ask was scoped to the heating-boost lever specifically, and
    DHW's own electric-addition behavior may differ enough to deserve its
    own look rather than reusing this threshold by assumption.

FIFTH LEVER — ACTIVE PRICE-PEAK REDUCTION (Fas 4e, 2026-09-26)
    Every existing branch of decide_heating_boost() is reactive-or-better:
    it either does nothing (0 offset, the pump's own neutral) or spends a
    little extra energy now to bank comfort/savings for later. None of them
    ever ask for LESS heat than the pump's own curve would already deliver.
    Item 1 of the 2026-09-26 competitive scan's recommendation list closes
    that gap: during a genuinely expensive period, actively pull the curve
    offset negative (heat_offset_reduction_c, a new, independent constant —
    not the boost constant's sign flipped, so the two magnitudes can be
    tuned separately) rather than only ever holding at neutral.

    "Genuinely expensive" uses the same percentile-of-known-prices shape as
    every other price check in this module — expensive_price_percentile
    (default DEFAULT_EXPENSIVE_PRICE_PERCENTILE) against
    today_prices_ore_per_kwh, the same reference list cheap_price_percentile
    already uses, just the opposite tail of the distribution. Gated by its
    own nibe.price_reduction_enabled opt-in flag, same nested-flag shape as
    dhw_luxury_enabled and price_spike_boost_enabled — off by default,
    changes nothing for anyone until explicitly turned on.

    Checked AFTER the three boost branches (solar / cheap-price / spike) —
    if any of those already justified a boost, the price is by definition
    not in today's expensive tail, so this never has a chance to override
    a boost; it only ever fires when none of the boost exceptions applied.

    Deliberately placed OUTSIDE the degree-minutes floor's gate (FOURTH
    LEVER above): that floor exists specifically to stop this module from
    asking the compressor to work harder than it should — a negative
    offset asks it to work LESS, which can never be what the DM floor is
    protecting against. A pump already deep in negative degree-minutes is
    exactly when reducing demand during an expensive hour is most welcome,
    not a reason to withhold it. The floor therefore continues to gate the
    three boost branches only; the reduction branch runs regardless of
    degree_minutes.

SIXTH — UPGRADE HYSTERESIS / ANTI-FLAP (Fas 4e, 2026-09-26, cross-cutting)
    Item 2 of the same recommendation list, directly inspired by
    tengmo-ab/smart-heat-control's own production-validated pattern (their
    write-up reports two years of use): an instant downgrade is always
    safe, but an instant upgrade right after a downgrade (or vice versa,
    repeatedly) risks flapping the curve offset back and forth every poll
    cycle whenever a price/solar/DM reading sits right at a threshold —
    wasted compressor cycling for no real comfort or savings benefit.

    Applied as a thin wrapper around the *comfort* outcome only — solar /
    cheap-price / spike / expensive-reduction / normal — never around the
    hard safety statuses (no_data, watchdog_reset, no_headroom,
    blocked_low_degree_minutes), which must always take effect immediately
    regardless of how recently the offset last changed; safety is not
    subject to a cooldown.

    An "upgrade" is any move to a heat_offset_c value HIGHER than
    previous_heat_offset_c (the caller's last-applied value, tracked in
    backend/app.py) — that covers economy/normal both moving up, and also
    a reduction (negative) moving back up to neutral or a boost. A
    "downgrade" (equal or lower) always applies at once, same as
    tengmo-ab's "instant downgrade" half of the pattern. An upgrade within
    upgrade_cooldown_s (default DEFAULT_UPGRADE_COOLDOWN_S, 20 minutes —
    matching tengmo-ab's own reported figure) of the last change is
    suppressed: the decision reports "suppressed_anti_flap" and holds at
    previous_heat_offset_c instead of the natural target, until the
    cooldown lapses.

    Both previous_heat_offset_c and seconds_since_offset_last_changed
    default to None (no suppression possible without proof there's
    something to suppress against) — same burden-of-proof convention as
    every other input here: a fresh add-on start, or a caller that hasn't
    wired the new state tracking yet, must never be treated as "just
    changed the offset a moment ago."

SEVENTH — LEGIONELLA / DISINFECTION GUARD ON DHW ECONOMY (Fas 4e, 2026-09-26)
    Item 3 of the same list, inspired by tvofi/heatpump_optimizer's
    treatment of legionella disinfection as a non-negotiable constraint on
    its own cost-optimizing MPC engine — a health safeguard that overrides
    the cost objective, not one more input weighed against it.

    decide_dhw_luxury() already resolves "no exception proven" to Economy,
    and Håkan's own rule ("Kostnadsbesparingen är alltid prioritet ett")
    means Economy can legitimately persist for a long stretch whenever
    prices/solar/headroom just never line up — that's the intended
    behavior for cost, but continuously-Economy DHW is also the one
    scenario where stored water could plausibly sit below a disinfection
    temperature for an extended period. This module has no visibility into
    Håkan's pump's actual water temperature or its firmware's own
    legionella handling (most Nibe firmware performs this internally
    regardless of comfort-mode setting — this guard is UNCONFIRMED
    defense-in-depth on top of that, not a substitute for it, and not a
    verified fact about this specific installation).

    Tracks seconds_since_last_non_economy (caller-supplied, mirroring
    seconds_since_last_nibe_contact's shape) against
    max_continuous_economy_s (default DEFAULT_MAX_CONTINUOUS_ECONOMY_S, a
    conservative 3 days — chosen as a defense-in-depth guess, not a
    measured legionella-risk interval; Nibe's own guidance, if any exists
    for this model, should supersede it once found). Once exceeded, forces
    comfort_mode="normal" for at least one cycle — deliberately Normal, not
    Luxury: this is a safety floor, not a comfort/cost reward, so it should
    do the minimum needed and no more.

    Applied to BOTH of decide_dhw_luxury()'s Economy-resolving branches
    (no_headroom and economy_no_condition) — deliberately overriding
    governor headroom too, unlike every other check in this module. This
    is the one place a genuinely uncertain safety concern is judged to
    outweigh the peak-governor's fuse budget; it fires at most once every
    max_continuous_economy_s (a period measured in days, not minutes), so
    the added load is rare and brief by construction. Missing
    seconds_since_last_non_economy (None — fresh start, or a caller that
    hasn't wired the tracking yet) does not trigger the guard — same
    burden-of-proof convention as everywhere else: no evidence of a long
    Economy stretch is not evidence of one.

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

EIGHTH LEVER — INDOOR-TEMPERATURE CEILING, A SECOND GATE (Fas 4f, 2026-10-09)
    Found during a Håkan-requested two-day operations review (2026-10-09):
    number.heat_offset_s1_47011 had sat at +2 almost continuously for ~44
    hours (2026-10-07 22:45 to 2026-10-09 17:49, one short gap for an
    unrelated Modbus outage), because cheap_price_percentile=0.5 means
    "cheaper than today's median" — true of roughly half of every day's
    hours by construction, often in one contiguous overnight block — and
    nothing in this module ever considered actual comfort need before this.
    Indoor temperature (climate.f750_climate_system_s1's
    current_temperature) climbed to 24.7°C against a 21.5°C target over
    that stretch: real energy spent overheating the house well past
    comfort, not a short, targeted pre-heat ahead of a price peak.

    The very first design draft for this module (the pre-H.E.M. pyscript
    prototype, claude/nibe_price_control.py) already had exactly this
    safeguard — MIN_INDOOR_TEMP/MAX_INDOOR_TEMP, "comfort override always
    wins over price optimization" — but it was never carried into this
    package's rewrite. This lever reinstates the MAX_INDOOR_TEMP half of
    that idea (the MIN half is a separate, not-yet-built concern: nothing
    here currently stops the pump from running too COLD, only too hot).

    Gate, not an exception, same shape as the FOURTH LEVER's degree-minutes
    floor: indoor_temp_c >= max_indoor_temp_c blocks the three BOOST
    branches (solar / cheap-price / spike) only, checked alongside
    dm_blocked, never the FIFTH LEVER's price-reduction branch — a
    negative offset asks for LESS heat, which this ceiling has no reason
    to prevent; if anything a hot house is exactly when a price-driven
    reduction is welcome. heat_offset_c resolves to 0 (neutral), not
    negative — same "a ceiling only withholds, it doesn't demand" choice
    the degree-minutes floor already made. Bypasses anti-flap entirely,
    also mirroring the degree-minutes floor: a suppressed downgrade could
    otherwise leave a boost in place past the point the ceiling says it
    should stop.

    Not gated by its own nibe.*_enabled flag — live as soon as nibe.enabled
    itself is on, same "a safety/comfort floor doesn't need a separate
    switch" precedent as degree_minutes_floor and upgrade_cooldown_s above.
    Unlike those two, though, this one is NOT a no-behavior-change-on-
    upgrade default: DEFAULT_MAX_INDOOR_TEMP_C (22.5°C) is deliberately set
    to actually engage given Håkan's own observed 23-24.7°C stretch — the
    whole point of adding it now is to change that behavior, not preserve
    it. Missing indoor_temp_c (None — entity unavailable, HA unreachable)
    does not block, same burden-of-proof convention as every other input
    in this module: no evidence the house is too warm is not evidence that
    it is.

    When both dm_blocked and the indoor-temperature ceiling would block
    the same cycle, the indoor-temperature reason is reported — it's the
    more directly actionable one for whoever reads the dashboard status,
    and nothing is lost: both still correctly veto every boost branch.
"""

from dataclasses import dataclass

DEFAULT_CHEAP_PRICE_PERCENTILE = 0.5  # cheaper half of today's known hours — same default as core.zaptec.scheduler
DEFAULT_MIN_SOLAR_SURPLUS_KW = 0.0
DEFAULT_HEADROOM_MARGIN_KW = 0.0  # v1 scope: any positive headroom counts, no safety buffer beyond target_kw itself

# Local copies of controller.py's own DHW_COMFORT_MODE_LUXURY/_ECONOMY
# strings. Not imported from there on purpose — this module stays
# dependency-free (no HA/requests import), same reasoning as every other
# module docstring here. Only used to recognize the raw register values
# decide_dhw_luxury() needs to react to while disabled (see its own
# docstring: 2026-10-07 fix for LUXURY, widened to ECONOMY 2026-10-09).
_RAW_COMFORT_MODE_LUXURY = "LUXURY"
_RAW_COMFORT_MODE_ECONOMY = "ECONOMY"

# Fas 4b (2026-09-24) — the watchdog controller.py's own docstring calls a
# "hard requirement before this runs beyond demo mode". 15 minutes: long
# enough that a normal transient (HA restart, brief network hiccup) never
# trips it, short enough that a genuinely lost connection doesn't leave a
# stuck curve-offset boost in place for the rest of a heating season.
DEFAULT_WATCHDOG_TIMEOUT_S = 900

# The register (number.heat_offset_s1_47011) allows -10..+10 in steps of 1,
# but this module only ever asks for a small, conservative nudge — not the
# full range a person adjusting the pump's own menu might use. +2 was
# chosen as "noticeably more heat, nowhere near an aggressive setting";
# revisit only after a season of real (demo_mode=False) data, not on a
# guess.
DEFAULT_HEAT_OFFSET_BOOST_C = 2
MAX_SAFE_HEAT_OFFSET_C = 2  # decision-layer ceiling; controller.py clamps again, defense in depth

# Fas 4c (2026-09-25) — predictive pre-heat, see module docstring's THIRD
# LEVER section. 6h sits inside the 1-8h window the Smart-NIBE-Control
# project reports using for the same idea — long enough to catch a typical
# evening price ramp starting from an afternoon tick, short enough that
# "pre-heating" doesn't start most of a day early.
DEFAULT_PRICE_SPIKE_LOOKAHEAD_HOURS = 6.0

# Top 15% of all currently-known (today + tomorrow) quarter-hour prices
# counts as a genuine "spike" worth pre-heating for — deliberately stricter
# than DEFAULT_CHEAP_PRICE_PERCENTILE's 50th-percentile cheap threshold,
# because this lever is reacting to the *other* tail of the distribution
# and a false positive costs real energy (heating the buffer for a price
# rise that turns out to be unremarkable), not just a missed discount.
DEFAULT_PRICE_SPIKE_PERCENTILE = 0.85

# Even a price in the top percentile might barely differ from right now on
# a flat-price day — require the upcoming peak to be at least this much
# pricier than the current price, in öre/kWh, before it's worth spending
# energy pre-heating for. 30 öre/kWh is a conservative first guess (a
# clearly noticeable swing, not a rounding-error one); revisit after a
# season of real data, same as DEFAULT_HEAT_OFFSET_BOOST_C.
DEFAULT_PRICE_SPIKE_MIN_DELTA_ORE = 30.0

# Fas 4d (2026-09-26) — see module docstring's FOURTH LEVER section for the
# full reasoning. Explicitly a conservative first guess, not a measured
# value: Håkan's live reading was -40 DM at the time this was written, and
# his installer's own electric-addition threshold (menu 5.1.x) is unknown.
# -400 DM leaves comfortable margin above that baseline while matching the
# order of magnitude the Smart-NIBE-Control project uses for the same
# purpose. Revisit once real DM history has accumulated.
DEFAULT_DEGREE_MINUTES_FLOOR = -400.0

# Fas 4e (2026-09-26) — see module docstring's FIFTH LEVER section. Top 15%
# of today's known prices, mirroring DEFAULT_PRICE_SPIKE_PERCENTILE's own
# choice of tail-strictness (the spike check looks forward at upcoming
# prices; this one looks at whether *right now* is already in that
# expensive tail) — deliberately the same value so "genuinely expensive"
# means the same thing whether this module is looking ahead or looking at
# the present.
DEFAULT_EXPENSIVE_PRICE_PERCENTILE = 0.85

# A separate, independently-tunable magnitude from DEFAULT_HEAT_OFFSET_BOOST_C
# — not just its sign flipped — so boost and reduction can be tuned apart
# once real data justifies either. -2 mirrors the boost lever's own "small,
# noticeably-different, nowhere near aggressive" sizing philosophy; the
# register's -10..+10 range technically allows much more.
DEFAULT_HEAT_OFFSET_REDUCTION_C = -2

# Fas 4e (2026-09-26) — see module docstring's SIXTH section. 20 minutes,
# matching tengmo-ab/smart-heat-control's own reported figure from two
# years of production use of the identical "instant downgrade, cooldown on
# upgrade" pattern.
DEFAULT_UPGRADE_COOLDOWN_S = 1200

# Fas 4e (2026-09-26) — see module docstring's SEVENTH section. A
# conservative, explicitly-unconfirmed defense-in-depth guess (3 days), not
# a measured legionella-risk interval for this specific pump/installation —
# revisit if Nibe's own documented guidance for this model is ever found.
DEFAULT_MAX_CONTINUOUS_ECONOMY_S = 259200.0

# Fas 4f (2026-10-09) — see module docstring's EIGHTH LEVER section. 22.5°C
# matches the original pyscript prototype's MAX_INDOOR_TEMP, and sits 1°C
# above Håkan's observed 21.5°C climate target — enough headroom that a
# normal, brief overshoot doesn't fight the boost lever, but low enough to
# actually have stopped the 24.7°C stretch this lever was added because of.
DEFAULT_MAX_INDOOR_TEMP_C = 22.5


@dataclass(frozen=True)
class HeatingBoostDecision:
    """Whether the space-heating curve-offset lever should be engaged this cycle.

    status: "no_data" | "watchdog_reset" | "no_headroom" |
        "blocked_low_degree_minutes" | "blocked_high_indoor_temp" |
        "engaged_cheap_price" | "engaged_solar_surplus" |
        "engaged_price_spike_ahead" | "reduced_expensive_price" |
        "suppressed_anti_flap" | "normal"
    heat_offset_c: the value to write to number.heat_offset_s1_47011 —
        DEFAULT_HEAT_OFFSET_BOOST_C while boosting (any of the three
        "engaged_*" statuses), DEFAULT_HEAT_OFFSET_REDUCTION_C while
        actively reducing ("reduced_expensive_price"), the held-over
        previous value while anti-flap is suppressing an upgrade
        ("suppressed_anti_flap"), 0 for Normal, watchdog_reset,
        blocked_low_degree_minutes, or blocked_high_indoor_temp (see
        module docstring's EIGHTH LEVER section), None only for no_data
        (don't touch the register at all that cycle).
    """

    status: str
    heat_offset_c: int | None
    reason: str


@dataclass(frozen=True)
class DhwLuxuryDecision:
    """Whether DHW should be in Luxury or Economy comfort mode this cycle.

    status: "disabled" | "disabled_reset_from_luxury" |
        "disabled_reset_from_economy" | "no_headroom" | "luxury_cheap_price"
        | "luxury_solar_surplus" | "economy_no_condition"
        | "forced_normal_legionella_guard"
    comfort_mode: "luxury" | "economy" | "normal" | None (None when disabled
        AND the register isn't currently stuck on Luxury or Economy — the
        caller must leave it untouched entirely in that case, the same
        "off = don't even read" contract governor/ev_scheduler use for their
        own enabled flags). "normal" appears for
        "forced_normal_legionella_guard" (see module docstring's SEVENTH
        section) and for "disabled_reset_from_luxury" /
        "disabled_reset_from_economy" (bug found 2026-10-07, widened
        2026-10-09: turning the dashboard toggle off used to leave the
        register exactly where it last was, so if this lever had pushed
        Luxury before being switched off, the pump stayed in Luxury — and
        therefore at its warmer target-temperature band — indefinitely, with
        nothing to ever pull it back down. The 2026-10-07 fix only caught
        that Luxury case; a real incident on 2026-10-09 showed the same
        thing happening with Economy — the toggle was switched on, this
        lever's own "no cheap-price/solar exception" fallback (see
        economy_no_condition below) landed on Economy within 20 minutes,
        and turning the toggle back off hours later left it stuck there
        (~45°C hot water) because the old check only recognised a stray
        LUXURY as "ours to clean up". Economy gets the identical treatment
        now.). This module never chooses Normal for cost/comfort reasons on
        its own — only as one of these three safety/correctness overrides.
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
    seconds_since_last_nibe_contact: float | None = None,
    cheap_price_percentile: float = DEFAULT_CHEAP_PRICE_PERCENTILE,
    min_solar_surplus_kw: float = DEFAULT_MIN_SOLAR_SURPLUS_KW,
    headroom_margin_kw: float = DEFAULT_HEADROOM_MARGIN_KW,
    heat_offset_boost_c: int = DEFAULT_HEAT_OFFSET_BOOST_C,
    watchdog_timeout_s: float = DEFAULT_WATCHDOG_TIMEOUT_S,
    price_spike_boost_enabled: bool = False,
    upcoming_prices_ore_per_kwh: list[float] | None = None,
    all_known_prices_ore_per_kwh: list[float] | None = None,
    price_spike_percentile: float = DEFAULT_PRICE_SPIKE_PERCENTILE,
    price_spike_min_delta_ore: float = DEFAULT_PRICE_SPIKE_MIN_DELTA_ORE,
    degree_minutes: float | None = None,
    degree_minutes_floor: float = DEFAULT_DEGREE_MINUTES_FLOOR,
    price_reduction_enabled: bool = False,
    expensive_price_percentile: float = DEFAULT_EXPENSIVE_PRICE_PERCENTILE,
    heat_offset_reduction_c: int = DEFAULT_HEAT_OFFSET_REDUCTION_C,
    previous_heat_offset_c: int | None = None,
    seconds_since_offset_last_changed: float | None = None,
    upgrade_cooldown_s: float = DEFAULT_UPGRADE_COOLDOWN_S,
    indoor_temp_c: float | None = None,
    max_indoor_temp_c: float = DEFAULT_MAX_INDOOR_TEMP_C,
) -> HeatingBoostDecision:
    """Pure decision for the space-heating curve-offset comfort-boost lever.

    seconds_since_last_nibe_contact: how long since NibeController last
        confirmed a successful read from the pump (its own
        seconds_since_last_contact()), or None if no read has succeeded yet
        since this add-on started. Only consulted in the headroom-unknown
        branch below — see the watchdog note there for why.

    price_spike_boost_enabled: nibe.price_spike_boost_enabled — the
        predictive pre-heat lever's own opt-in flag (see module docstring's
        THIRD LEVER section). False (the shipped default) means the three
        params below are never even consulted — same "off = don't even
        read" contract dhw_luxury_enabled uses in decide_dhw_luxury.
    upcoming_prices_ore_per_kwh: forward-looking quarter-hour prices
        starting just after the current period, already windowed to the
        lookahead horizon by the caller (backend/app.py) — this function
        does no date/time math itself, same as every other input here.
        None or empty (e.g. no forward price data published yet) simply
        skips this exception for the cycle.
    all_known_prices_ore_per_kwh: all currently-known prices (typically
        today + tomorrow) used only as the reference set for
        price_spike_percentile. Falls back to upcoming_prices_ore_per_kwh
        itself when not provided — a narrower but still well-defined
        threshold, not a fatal condition.
    degree_minutes: live number.degree_minutes_16_bit_43005 reading (see
        module docstring's FOURTH LEVER section), or None if unavailable.
        A gate, not an exception — checked right after governor headroom,
        before any of the three boost exceptions below, so it can only
        suppress a boost, never cause one. None (missing data) does not
        block — same burden-of-proof convention as everywhere else here.
        Does NOT gate the price-reduction branch below (see FIFTH LEVER in
        the module docstring) — a negative offset only reduces compressor
        demand, which this floor has no reason to prevent.
    price_reduction_enabled: nibe.price_reduction_enabled — the active
        price-peak reduction lever's own opt-in flag (see module
        docstring's FIFTH LEVER section). False (the shipped default) means
        expensive_price_percentile/heat_offset_reduction_c are never
        consulted, same "off = don't even read" contract as
        price_spike_boost_enabled.
    previous_heat_offset_c, seconds_since_offset_last_changed,
        upgrade_cooldown_s: anti-flap/hysteresis inputs (see module
        docstring's SIXTH section) — suppress an *increase* in offset
        relative to previous_heat_offset_c when it would happen within
        upgrade_cooldown_s of the last change. Both state inputs default to
        None (no suppression without proof there's something to suppress
        against). Never applied to the hard safety statuses above
        (no_data, watchdog_reset, no_headroom, blocked_low_degree_minutes,
        blocked_high_indoor_temp) — only to the comfort outcome below.
    indoor_temp_c: live climate.f750_climate_system_s1 current_temperature
        reading (see module docstring's EIGHTH LEVER section), or None if
        unavailable. A gate, not an exception — checked alongside the
        degree-minutes floor, before any of the three boost exceptions
        below, so it can only suppress a boost, never cause one. Never
        gates the price-reduction branch further down — a negative offset
        only reduces compressor demand, which an indoor-temperature
        ceiling has no reason to prevent. None (missing data) does not
        block — same burden-of-proof convention as everywhere else here.
    max_indoor_temp_c: the ceiling indoor_temp_c is compared against.
        Defaults to DEFAULT_MAX_INDOOR_TEMP_C.
    """
    headroom = _headroom_available(
        governor_enabled=governor_enabled,
        current_kw=current_kw,
        target_kw=target_kw,
        margin_kw=headroom_margin_kw,
    )
    if headroom is None:
        # Watchdog (Fas 4b): headroom being unprovable is the one case a
        # stuck non-zero offset can persist indefinitely (see
        # controller.py's "NO FAIL-SAFE ON DISCONNECT"), because it's the
        # only branch that can repeatedly return heat_offset_c=None
        # ("don't touch the register") cycle after cycle. If the pump
        # itself has also been unreachable for a long stretch — not just
        # this cycle's headroom reading, but no confirmed contact at all
        # — force the register back to neutral instead of leaving
        # whatever it was last set to in place.
        #
        # seconds_since_last_nibe_contact is None right after startup
        # (no read has succeeded yet) — deliberately NOT treated as a
        # timeout, same "burden of proof" convention as the price/solar
        # exceptions above: no evidence of a problem yet is not evidence
        # of one.
        if (
            seconds_since_last_nibe_contact is not None
            and seconds_since_last_nibe_contact >= watchdog_timeout_s
        ):
            return HeatingBoostDecision(
                status="watchdog_reset",
                heat_offset_c=0,
                reason=(
                    f"no confirmed contact with the pump for "
                    f"{seconds_since_last_nibe_contact:.0f}s "
                    f"(>= {watchdog_timeout_s:.0f}s) while headroom is "
                    "unknown — forcing curve offset back to neutral"
                ),
            )
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

    # Fas 4d gate: can only suppress the three BOOST branches just below,
    # never the price-reduction branch further down (see FIFTH LEVER in the
    # module docstring) — a negative offset only reduces compressor demand,
    # which this floor has no reason to block. Tracked as a flag rather
    # than returning immediately so the reduction branch still gets a
    # chance to run before this module falls back to reporting the block.
    dm_blocked = degree_minutes is not None and degree_minutes <= degree_minutes_floor

    # Fas 4f gate (EIGHTH LEVER): same shape and same "can only suppress a
    # boost, never cause one" contract as dm_blocked above — see the module
    # docstring for the full reasoning.
    indoor_temp_blocked = (
        indoor_temp_c is not None and indoor_temp_c >= max_indoor_temp_c
    )

    natural: HeatingBoostDecision | None = None

    if not dm_blocked and not indoor_temp_blocked:
        if solar_surplus_kw is not None and solar_surplus_kw > min_solar_surplus_kw:
            natural = HeatingBoostDecision(
                status="engaged_solar_surplus",
                heat_offset_c=heat_offset_boost_c,
                reason=(
                    f"{solar_surplus_kw:.2f}kW solar surplus would otherwise be "
                    f"exported — boosting heat curve by +{heat_offset_boost_c}"
                ),
            )

        if natural is None and spot_price_ore_per_kwh is not None and today_prices_ore_per_kwh:
            threshold = _percentile(today_prices_ore_per_kwh, cheap_price_percentile)
            if spot_price_ore_per_kwh <= threshold:
                natural = HeatingBoostDecision(
                    status="engaged_cheap_price",
                    heat_offset_c=heat_offset_boost_c,
                    reason=(
                        f"price {spot_price_ore_per_kwh:.1f} öre <= {threshold:.1f} öre "
                        f"(cheapest {cheap_price_percentile:.0%} of today) — boosting heat "
                        f"curve by +{heat_offset_boost_c}"
                    ),
                )

        if (
            natural is None
            and price_spike_boost_enabled
            and spot_price_ore_per_kwh is not None
            and upcoming_prices_ore_per_kwh
        ):
            reference_prices = all_known_prices_ore_per_kwh or upcoming_prices_ore_per_kwh
            spike_threshold = _percentile(reference_prices, price_spike_percentile)
            upcoming_peak = max(upcoming_prices_ore_per_kwh)
            delta_ore = upcoming_peak - spot_price_ore_per_kwh
            if upcoming_peak >= spike_threshold and delta_ore >= price_spike_min_delta_ore:
                natural = HeatingBoostDecision(
                    status="engaged_price_spike_ahead",
                    heat_offset_c=heat_offset_boost_c,
                    reason=(
                        f"upcoming price {upcoming_peak:.1f} öre >= {spike_threshold:.1f} "
                        f"öre (top {1 - price_spike_percentile:.0%} of known prices) and "
                        f"{delta_ore:.1f} öre above the current "
                        f"{spot_price_ore_per_kwh:.1f} öre — pre-heating by "
                        f"+{heat_offset_boost_c} ahead of it"
                    ),
                )

    # Fas 4e, FIFTH LEVER — active price-peak reduction. Runs whether or not
    # dm_blocked, and only when none of the three boost branches above
    # already fired (a boost, if proven, always takes priority).
    if (
        natural is None
        and price_reduction_enabled
        and spot_price_ore_per_kwh is not None
        and today_prices_ore_per_kwh
    ):
        expensive_threshold = _percentile(today_prices_ore_per_kwh, expensive_price_percentile)
        if spot_price_ore_per_kwh >= expensive_threshold:
            natural = HeatingBoostDecision(
                status="reduced_expensive_price",
                heat_offset_c=heat_offset_reduction_c,
                reason=(
                    f"price {spot_price_ore_per_kwh:.1f} öre >= {expensive_threshold:.1f} öre "
                    f"(most expensive {1 - expensive_price_percentile:.0%} of today) — "
                    f"reducing heat curve by {heat_offset_reduction_c}"
                ),
            )

    if natural is None and (dm_blocked or indoor_temp_blocked):
        # Hard safety status — bypasses anti-flap entirely (see SIXTH
        # section in the module docstring): a suppressed downgrade could
        # otherwise leave a boost in place past the point the gate says it
        # should stop. When both gates are active, the indoor-temperature
        # reason is reported (see EIGHTH LEVER in the module docstring) —
        # both still correctly veto every boost branch either way.
        if indoor_temp_blocked:
            return HeatingBoostDecision(
                status="blocked_high_indoor_temp",
                heat_offset_c=0,
                reason=(
                    f"indoor temp {indoor_temp_c:.1f}°C >= ceiling "
                    f"{max_indoor_temp_c:.1f}°C — house is already warm "
                    "enough, staying at neutral offset regardless of price"
                ),
            )
        return HeatingBoostDecision(
            status="blocked_low_degree_minutes",
            heat_offset_c=0,
            reason=(
                f"degree minutes {degree_minutes:.0f} <= floor "
                f"{degree_minutes_floor:.0f} — compressor is already under "
                "enough load that boosting further risks triggering "
                "electric addition, staying at neutral offset"
            ),
        )

    if natural is None:
        natural = HeatingBoostDecision(
            status="normal",
            heat_offset_c=0,
            reason=(
                "no cheap-price, solar-surplus, upcoming-spike, or "
                "expensive-price exception proven — staying at neutral offset"
            ),
        )

    return _apply_anti_flap(
        natural,
        previous_heat_offset_c=previous_heat_offset_c,
        seconds_since_offset_last_changed=seconds_since_offset_last_changed,
        upgrade_cooldown_s=upgrade_cooldown_s,
    )


def _apply_anti_flap(
    natural: HeatingBoostDecision,
    *,
    previous_heat_offset_c: int | None,
    seconds_since_offset_last_changed: float | None,
    upgrade_cooldown_s: float,
) -> HeatingBoostDecision:
    """Suppress an *increase* in heat_offset_c relative to
    previous_heat_offset_c when it would happen within upgrade_cooldown_s
    of the last change — see module docstring's SIXTH section. Downgrades
    (equal or lower) always apply immediately, mirroring
    tengmo-ab/smart-heat-control's own "instant downgrade" half of the
    pattern. Only ever called with a *comfort* outcome (solar / cheap-price
    / spike / expensive-reduction / normal) — never with a hard safety
    status, which the caller returns directly without going through here.
    """
    if previous_heat_offset_c is None or seconds_since_offset_last_changed is None:
        # No proof there's a recent change to suppress against — same
        # burden-of-proof convention as every other input in this module.
        return natural
    if natural.heat_offset_c is None or natural.heat_offset_c <= previous_heat_offset_c:
        return natural
    if seconds_since_offset_last_changed >= upgrade_cooldown_s:
        return natural
    return HeatingBoostDecision(
        status="suppressed_anti_flap",
        heat_offset_c=previous_heat_offset_c,
        reason=(
            f"upgrade from {previous_heat_offset_c} to {natural.heat_offset_c} "
            f"({natural.status}) suppressed — only "
            f"{seconds_since_offset_last_changed:.0f}s since the offset last "
            f"changed (< {upgrade_cooldown_s:.0f}s cooldown); holding at "
            f"{previous_heat_offset_c}"
        ),
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
    seconds_since_last_non_economy: float | None = None,
    max_continuous_economy_s: float = DEFAULT_MAX_CONTINUOUS_ECONOMY_S,
    current_comfort_mode: str | None = None,
) -> DhwLuxuryDecision:
    """Pure decision for the "Lyxläge varmvatten" dashboard toggle.

    `enabled` is the dashboard switch itself (nibe.dhw_luxury_enabled in
    settings_store) — when off, this is normally a deliberate no-op:
    comfort_mode is None and the caller must not touch the register at all,
    so a manual choice made on the pump's own panel (Economy, Normal, Smart
    Control) is never fought.

    `current_comfort_mode`: the register's raw, currently-read value (e.g.
    "LUXURY"/"ECONOMY"/"NORMAL"/"SMART CONTROL", case-insensitive), or None
    if unavailable. Only consulted while `enabled` is False, and only to
    catch two failure modes, both the same shape: this lever wrote a value
    while on, the dashboard toggle was then switched off, and "off" only
    ever meant "stop asking for a Luxury/Economy exception", never "undo
    what I already asked for" — so the pump stayed stuck wherever this
    lever last left it, with nothing to pull it back down.

    - Found 2026-10-07: pushed to Luxury, then disabled the same day — stuck
      in Luxury (and its warmer 58-64°C target band) for two days.
    - Found 2026-10-09 (real incident): enabled with no cheap-price/solar
      exception active, so economy_no_condition below landed it on Economy
      within 20 minutes — then disabled a few hours later, leaving the pump
      stuck on Economy (~45°C hot water) because the 2026-10-07 fix only
      recognised a stray LUXURY as this lever's own residue.

    If the register is found sitting on either Luxury or Economy while
    disabled, this now resets it to Normal once; any other value (including
    a deliberate manual Luxury/Economy choice made without this toggle) is
    still left completely untouched, matching the original "don't fight the
    panel" intent — the same trade-off the original 2026-10-07 fix already
    accepted for Luxury (a genuine manual Luxury selection on the panel
    would be reset too, if the toggle happens to be off), now applied
    symmetrically to Economy.

    seconds_since_last_non_economy, max_continuous_economy_s: legionella/
        disinfection guard (see module docstring's SEVENTH section) —
        forces comfort_mode="normal" instead of "economy" once continuous
        Economy time exceeds max_continuous_economy_s, overriding governor
        headroom too. seconds_since_last_non_economy defaults to None (no
        override without proof of a long Economy stretch) — the caller
        (backend/app.py) is responsible for tracking the actual elapsed
        time; this function does no date/time math itself.
    """
    if not enabled:
        raw_mode = (current_comfort_mode or "").strip().upper()
        if raw_mode == _RAW_COMFORT_MODE_LUXURY:
            return DhwLuxuryDecision(
                status="disabled_reset_from_luxury",
                comfort_mode="normal",
                reason=(
                    "Lyxläge varmvatten is off, but the pump is still stuck on "
                    "Luxury from before it was switched off — resetting to Normal"
                ),
            )
        if raw_mode == _RAW_COMFORT_MODE_ECONOMY:
            return DhwLuxuryDecision(
                status="disabled_reset_from_economy",
                comfort_mode="normal",
                reason=(
                    "Lyxläge varmvatten is off, but the pump is still stuck on "
                    "Economy from this lever's own no-condition fallback before "
                    "it was switched off — resetting to Normal"
                ),
            )
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
        return _apply_legionella_guard(
            DhwLuxuryDecision(status="no_headroom", comfort_mode="economy", reason=reason),
            seconds_since_last_non_economy=seconds_since_last_non_economy,
            max_continuous_economy_s=max_continuous_economy_s,
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

    return _apply_legionella_guard(
        DhwLuxuryDecision(
            status="economy_no_condition",
            comfort_mode="economy",
            reason="no cheap-price or solar-surplus exception proven — Economy hot water",
        ),
        seconds_since_last_non_economy=seconds_since_last_non_economy,
        max_continuous_economy_s=max_continuous_economy_s,
    )


def _apply_legionella_guard(
    natural: DhwLuxuryDecision,
    *,
    seconds_since_last_non_economy: float | None,
    max_continuous_economy_s: float,
) -> DhwLuxuryDecision:
    """Force comfort_mode="normal" instead of "economy" once continuous
    Economy time exceeds max_continuous_economy_s — see module docstring's
    SEVENTH section. Only ever called with an Economy-resolving decision
    (no_headroom or economy_no_condition); a Luxury outcome is passed
    through untouched by never being routed here in the first place.
    """
    if natural.comfort_mode != "economy":
        return natural
    if seconds_since_last_non_economy is None:
        # No proof Economy has been continuous for a while — same
        # burden-of-proof convention as everywhere else in this module.
        return natural
    if seconds_since_last_non_economy < max_continuous_economy_s:
        return natural
    return DhwLuxuryDecision(
        status="forced_normal_legionella_guard",
        comfort_mode="normal",
        reason=(
            f"{seconds_since_last_non_economy:.0f}s continuously in Economy "
            f"(>= {max_continuous_economy_s:.0f}s guard) — forcing Normal for "
            "at least one cycle as a defense-in-depth legionella/"
            "disinfection safeguard, overriding both the cost-driven "
            f"Economy default ({natural.status}) and governor headroom"
        ),
    )


def _percentile(values: list[float], percentile: float) -> float:
    """Same nearest-rank percentile as core.zaptec.scheduler._percentile —
    duplicated rather than imported so this module has zero cross-package
    dependencies, same reasoning as peak_governor.py's own constants."""
    ordered = sorted(values)
    index = round(percentile * (len(ordered) - 1))
    return ordered[index]
