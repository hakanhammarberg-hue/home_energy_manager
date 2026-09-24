"""core.governor — the real-time household power cap (peak shaving / effekttariff).

STATUS: Fas 3b, in progress (2026-08-30) — EV lever only.

Roll i home-energy-manager (se home-energy-manager-alternative-architecture.md
§"Effektbegränsaren i den nya arkitekturen"): fristående realtidslager ovanpå
core.bess, core.zaptec och core.nibe — pollar core.perific och håller
totaleffekten under ett satt tak genom att strypa Zaptec först, blockera
Nibes eltillskott i andra hand. Behöver aldrig vara del av någon optimerares
matematik.

Modulstruktur:
    peak_governor.py — KLAR (2026-08-30): den rena beslutslogiken (decide()),
        portad från peak_power_governor.py:s EV-spak. Ingen HA, ingen
        pollning här — bara matematiken, 15 tester. Inkluderar en
        avsiktlig fix jämfört med originalet: en paus governorn orsakar
        återupptas också automatiskt av governorn när huset är under
        målet igen (bekräftat med Håkan 2026-08-30) — originalskriptet
        förlitade sig på Nibe-spakens vakt-timer-automation för det, vilket
        inte täcker en ren EV-paus alls.
    (nästa) en pollningsloop i backend/app.py, samma mönster som den
        befintliga schemaläggaren — läser core.perific + core.zaptec var
        ~30:e sekund, anropar peak_governor.decide(), och applicerar
        resultatet via ZaptecController (som redan är test_mode-spärrad,
        se core/zaptec/controller.py). Detta är det enda steget som
        faktiskt kan skriva till hårdvaran automatiskt.
    (därefter) inställningar/UI för på/av + target_kw, samt en
        statusindikator på Dashboard.

MEDVETET INTE MED I DEN HÄR FASEN
    Nibe-spaken (blockera elpatronen efter NIBE_LEVER_DELAY_CYCLES) - väntar
    på att LilyGO/ESPHome-gatewayen monteras, se core.nibe.
    Vakt-timer-logiken (timer.peak_governor_safety + dess fristående
    HA-automation) — den fanns specifikt för att en fastnad Nibe-spärr är en
    komfort-/säkerhetsfråga i kyla; EV-spaken ensam klassar originalskriptets
    egen dokumentation som "just an inconvenience... not a safety concern."
    Byggs tillbaka den dag Nibe-spaken byggs — se peak_governor.py:s
    docstring för hela resonemanget.

Redan bekräftade riktiga entiteter (2026-08-29) att koppla in i
pollningsloopen — se core.perific och core.zaptec för källorna. Nibe-hälften
av spaken (switch.nibe_electric_addition_blocked) väntar liksom core.nibe på
att gatewayen monteras.

Start-target: 12 kW (bekräftat med Håkan 2026-08-30 — 20A/3-fas
huvudsäkring = 13.8kW teoretiskt tak, 12kW lämnar marginal). Se
peak_governor.py:s DEFAULT_TARGET_KW.
"""
