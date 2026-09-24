"""core.zaptec — EV charging control for a Zaptec Go 2.

STATUS: controller.py (Fas 3a, 2026-08-29) — read/write capability, safety-
gated by test_mode (see that module's docstring). scheduler.py (Fas 5a,
2026-08-31) — the price/SOC/solar gate that decides *whether* a charging
session may run at all right now; pure decision logic only, same as
controller.py's writes, nothing calls it automatically yet. Fas 5b wires
scheduler.decide() into the same 30s poll loop as peak_governor, running
BEFORE it (see scheduler.py's own docstring for why gate-before, not merge).

Roll i home-energy-manager (se home-energy-manager-alternative-architecture.md
§"Föreslagen arkitektur"): egen, enklare beslutslogik jämte core.bess's
oförändrade DP-motor — inte gemensam optimering (Tolkning B, bekräftad av
Håkan 2026-08-29).

Modulstruktur:
    controller.py — KLAR (Fas 3a): laddström/paus, med samma test_mode-idiom
        som core.bess.ha_api_controller redan använder för Growatt.
    scheduler.py  — KLAR, ren beslutslogik (Fas 5a): SOC-tak (60%), solöver-
        skott/lågprisundantag över taket, engångs-override per laddsession,
        "aldrig batteri->bil"-spärren, samt enkel prisrankning under taket
        (ingen deadline, inget kWh-mål — v1-scope). Inte kopplad till HA
        eller ZaptecController än (Fas 5b).

Uttalat mål för Fas 5 (bekräftat av Håkan 2026-08-30): en kostnadsbesparings-
jämförelse för EV-laddningen — hur mycket billigare blev det att ladda
prisstyrt jämfört med att ladda utan hänsyn till pris — i samma anda som
core.bess.savings_aggregator redan gör för batteriet (Grid-Only Cost vs.
faktisk kostnad, synligt på Savings-sidan). Inte samma sak som
peak_governor.py:s effektstyrning ovan, som är en säkerhets-/undvikande-
funktion utan egen kronbesparing att räkna hem förrän en effekttariff
faktiskt är aktiverad på avtalet (se core/governor/__init__.py).

Bekräftade riktiga entiteter i Håkans HA-instans (2026-08-29) — OBS: Zaptec-
integrationen namnger allt efter laddarens serienummer, inte "zaptec":
    switch.gpn049831_laddar            — på/av (visar "unavailable" när
                                          ingen bil är inkopplad)
    sensor.gpn049831_laddstatus        — status ("disconnected" just nu)
    number.gpn049831_max_laddstrom     — skrivbar "tillgänglig/max laddström"
                                          (står på 16.0A — bekräfta om det är
                                          en verklig installationsgräns)
    number.gpn049831_min_laddstrom     — golv, 6.0A
    sensor.gpn049831_tilldelad_laddstrom — faktiskt tilldelad ström (läsning)

Bilbyte 2026-08-31: Håkan bytte elbil samma dag som Fas 5a byggdes. Gamla
Kia Niro-entiteterna (sensor.niro_ev_battery_level m.fl.) är raderade — nya
bilen heter "EV3" i HA, samma kia_uvo-integration, se scheduler.py:s
docstring för de nya entitets-ID:na (sensor.ev3_ev_battery_level,
binary_sensor.ev3_ev_battery_plug, m.fl.), bekräftade live samma dag.
"""
