"""core.perific — real-time site power reading from Perific One.

STATUS: Fas 1 skelett. Ingen logik implementerad ännu — det är Fas 2.

Roll i home-energy-manager (se home-energy-manager-alternative-architecture.md
§"Föreslagen arkitektur"): samma typ av datakälla som core.bess.PriceManager,
men för realtida eleffekt från den auktoritativa mätaren (HAN/P1), inte pris.
Läses av core.governor.peak_governor i Fas 3 och (senare) valfritt av
core.bess/core.nibe om de vill informeras av samma signal.

Bekräftad riktig entitet i Håkans HA-instans (2026-08-29):
    sensor.perific_one_perific_perific_one_power_total

Fas 2 lägger till reader.py här: en tunn wrapper runt Home Assistants
websocket/REST-API (samma mönster som core.bess.ha_api_controller använder
för Growatt) som exponerar aktuell effekt till resten av appen.
"""
