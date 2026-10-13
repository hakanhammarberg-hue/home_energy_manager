"""core.hardware_info — identification facts (serial numbers, firmware/
model versions, VIN, MAC) for every physical product in this installation,
for the dashboard's "Info om hårdvara" page (2026-10-13, built at Håkan's
direct request).

This is a standalone top-level module, not its own package like
core/nibe/ or core/perific/, because — unlike those — it isn't one
hardware domain's control/decision logic plus its own live read; it's a
single cross-cutting read that pulls a few identification entities from
EVERY domain this app already knows about (Nibe, Growatt/solax inverter +
battery, Zaptec charger, Kia vehicle, Perific One) into one page. Reusing
each domain's own entity-naming/read style here, rather than adding a
thin "identity" submodule under each of core/nibe, core/zaptec, etc.,
keeps all of this page's entity IDs and hardcoded facts in one place that
can be re-surveyed together the next time something changes.

Same "never fabricate a value" convention as core/nibe/live.py: a
live-fetched field is None whenever its entity is unavailable/unreachable
— never a fake empty string. A handful of fields are instead HARDCODED
string constants (manufacturer/model/device names) rather than read from
Home Assistant at all — each such constant is commented with exactly why:
it's a Home Assistant device-registry fact (confirmed via ha_get_device,
not reachable through this app's plain-REST-polling architecture) or a
device name embedded in every one of its entity IDs with no separate
"serial number" entity to read instead. These essentially never change,
so hardcoding them is the right call, same reasoning NIBE_HEAT_OFFSET_ENTITY
and friends in backend/app.py already use for their own static facts.

WHY INDIVIDUAL /api/states/<id> CALLS, NOT ONE /api/states DUMP
    Same reasoning as core/nibe/live.py's own docstring: Home Assistant's
    REST API has no "give me just these N entities" filter on the bulk
    /api/states endpoint, so one GET per entity (reusing a single
    requests.Session for connection keep-alive) stays proportional to what
    this page actually needs rather than pulling the whole state machine.
    This page has no polling cadence at all (identification facts don't
    change during a session — see useHardwareInfo.ts), so the cost here is
    smaller still: one manual fetch, a dozen-odd GETs, done.

Every entity ID below was confirmed live against Håkan's Home Assistant
instance on 2026-10-13.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

# --- Nibe F750 (heat pump) --------------------------------------------
# manufacturer/model are a Home Assistant device-registry fact (confirmed
# via ha_get_device, device_id 7ba5e1df5bac10a036fdd7c2302c99f2, 2026-10-13)
# — not reachable through this app's plain-REST-polling architecture and
# essentially never changes, so hardcoded rather than read.
NIBE_MANUFACTURER = "NIBE Energy Systems"
NIBE_MODEL = "F750 CU 3x400V"
NIBE_HW_VERSION_ENTITY = "sensor.nibe_inverter_hw_version_40331"
# Enabled moments before this module was written (2026-10-13); confirmed
# existing but reading "unavailable" right then — may populate after more
# uptime, or may stay unavailable, same "entity exists but has nothing to
# say yet" story as several registers in core/nibe/live.py. Treated exactly
# the same as every other field here: None when unavailable, never a
# fabricated placeholder.
NIBE_SW_VERSION_ENTITY = "sensor.software_version_43001"

# --- Inverter (växelriktare) — Growatt, via solax_modbus ---------------
# manufacturer is a Home Assistant device-registry fact (confirmed
# 2026-10-13) — hardcoded for the same reason as NIBE_MANUFACTURER above.
# The registry's model field is null for this device, so there is no
# INVERTER_MODEL constant — fetch_hardware_info() below leaves "model" as
# None rather than guessing a model string.
INVERTER_MANUFACTURER = "Growatt New Energy"
INVERTER_SERIAL_ENTITY = "sensor.garage_solaxgrowatt_inverter_serial_number"
INVERTER_FIRMWARE_ENTITY = "sensor.garage_solaxgrowatt_inverter_firmware_version"

# --- Battery (BMS + moduler) — same Growatt/solax_modbus device --------
# Only BMS 1 is physically connected right now (confirmed live 2026-10-13
# via BATTERY_BMS_CONNECTED_ENTITY's state, "BMS 1 Connected"), and only
# modules 1 and 2 under it have enabled serial-number entities — fetched
# explicitly below rather than discovered dynamically from the module-count
# register, since that's all that exists today; see fetch_hardware_info()'s
# own comment on the modules list for the "only include what actually
# resolved" rule that keeps this honest if a module ever goes away.
BATTERY_BMS_TYPE_ENTITY = "sensor.garage_solaxgrowatt_inverter_bms_type"
BATTERY_BMS1_SERIAL_ENTITY = "sensor.garage_solaxgrowatt_inverter_bms_1_serial_number"
BATTERY_BMS1_MONITORING_VERSION_ENTITY = (
    "sensor.garage_solaxgrowatt_inverter_bms_1_monitoring_version"
)
BATTERY_BMS1_MODULE_1_SERIAL_ENTITY = (
    "sensor.garage_solaxgrowatt_inverter_bms_1_module_1_serial_number"
)
BATTERY_BMS1_MODULE_2_SERIAL_ENTITY = (
    "sensor.garage_solaxgrowatt_inverter_bms_1_module_2_serial_number"
)
# Raw "BMS 1 Connected" / "BMS 2 Connected" / etc. state, surfaced as-is so
# the page gives an honest read of which BMS(es) are actually connected
# right now — that's what determines whether a second BMS/module set even
# has anything to show, not anything this module decides.
BATTERY_BMS_CONNECTED_ENTITY = "sensor.garage_solaxgrowatt_inverter_bms_s_connected"

# --- EV charger (laddare) — Zaptec Go2 ---------------------------------
# manufacturer/model are hardcoded: a Zaptec Go2 is what Håkan has, there's
# no HA entity that reports the model name back. deviceName is this
# charger's own serial/identity — "GPN049831" is embedded in every one of
# its entity IDs (see backend/app.py's ZAPTEC_* constants) and there is no
# separate serial-number entity to read instead, so it's hardcoded here the
# same way.
EV_CHARGER_MANUFACTURER = "Zaptec"
EV_CHARGER_MODEL = "Zaptec Go2"
EV_CHARGER_DEVICE_NAME = "GPN049831"
# An update.* entity, not a plain sensor — the value this page wants
# (installed_version) lives in its attributes, not its bare state (which
# is just "on"/"off" for "update available"/"up to date"). See attr_of()
# below, the same split core/nibe/live.py's own attr_of() makes for
# climate/DHW entities.
EV_CHARGER_UPDATE_ENTITY = "update.gpn049831_uppdatera_mjukvara"

# --- Vehicle — Kia EV3 --------------------------------------------------
# manufacturer/model hardcoded: no HA entity reports these back for a
# kia_uvo-integrated vehicle, same reasoning as the EV charger above.
VEHICLE_MANUFACTURER = "Kia Europe"
VEHICLE_MODEL = "EV3"
VEHICLE_VIN_ENTITY = "sensor.ev3_vehicle_identification_number"

# --- Perific One (power-metering device, core/perific/) ----------------
# manufacturer/model hardcoded, same reasoning as the EV charger/vehicle
# above. MAC address functions as Perific's hardware identifier here — no
# separate serial-number field exists for this device.
PERIFIC_ONE_MANUFACTURER = "Perific Technologies AB"
PERIFIC_ONE_MODEL = "Perific Max/One"
PERIFIC_ONE_MAC_ENTITY = "sensor.perific_one_perific_perific_one_mac_address"
PERIFIC_ONE_ITEM_ID_ENTITY = "sensor.perific_one_perific_perific_one_item_id"

# Every entity this page reads, fetched as one batch of individual GETs —
# see the module docstring for why individual GETs rather than a bulk dump.
_ALL_ENTITIES = [
    NIBE_HW_VERSION_ENTITY,
    NIBE_SW_VERSION_ENTITY,
    INVERTER_SERIAL_ENTITY,
    INVERTER_FIRMWARE_ENTITY,
    BATTERY_BMS_TYPE_ENTITY,
    BATTERY_BMS1_SERIAL_ENTITY,
    BATTERY_BMS1_MONITORING_VERSION_ENTITY,
    BATTERY_BMS1_MODULE_1_SERIAL_ENTITY,
    BATTERY_BMS1_MODULE_2_SERIAL_ENTITY,
    BATTERY_BMS_CONNECTED_ENTITY,
    EV_CHARGER_UPDATE_ENTITY,
    VEHICLE_VIN_ENTITY,
    PERIFIC_ONE_MAC_ENTITY,
    PERIFIC_ONE_ITEM_ID_ENTITY,
]


def _get_state(
    session: requests.Session, base_url: str, headers: dict, entity_id: str
) -> dict | None:
    """One entity's raw HA state dict, or None on any failure/unavailable
    state. Identical shape to core/nibe/live.py's own _get_state — kept as
    an independent copy rather than imported, same "two read paths, two
    independent copies" precedent backend/app.py already sets for its own
    duplicated entity constants, since core.nibe.live is scoped to the
    Nibe page and has no reason to be a dependency of this cross-domain
    module."""
    url = f"{base_url}/api/states/{entity_id}"
    try:
        response = session.get(url, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Could not reach Home Assistant for %s: %s", entity_id, e)
        return None

    try:
        data = response.json()
    except ValueError:
        return None

    if data.get("state") in ("unavailable", "unknown", None):
        return None
    return data


def fetch_hardware_info(base_url: str, headers: dict) -> dict:
    """Fetch every identification entity this page needs and return a
    nested, camelCase-keyed dict ready for the API response, grouped one
    key per physical product: nibe, inverter, battery, evCharger, vehicle,
    perificOne.

    Every live-fetched field is None whenever its entity is unavailable,
    unreachable, or 404s — never a fabricated placeholder — so the
    frontend can show "Ej tillgänglig" rather than a misleading value.
    Hardcoded manufacturer/model/device-name facts (see the constants
    above) are always present as plain strings since they don't depend on
    Home Assistant at all. One entity being down never blanks any other
    product's section — each product's fields resolve independently, same
    "a partial read still returns whatever did succeed" convention as
    core/nibe/live.py's fetch_live_snapshot.
    """
    session = requests.Session()
    try:
        plain: dict[str, dict | None] = {
            entity_id: _get_state(session, base_url, headers, entity_id)
            for entity_id in _ALL_ENTITIES
        }
    finally:
        session.close()

    def state_of(entity_id: str) -> str | None:
        data = plain.get(entity_id)
        if data is None:
            return None
        return data.get("state")

    def attr_of(entity_id: str, attribute: str) -> str | None:
        """Like state_of, but for a value that lives in an entity's
        attributes rather than its bare state — the Zaptec update.*
        entity's installed_version, same split core/nibe/live.py's own
        attr_of() makes for climate/DHW entities."""
        data = plain.get(entity_id)
        if data is None:
            return None
        value = (data.get("attributes") or {}).get(attribute)
        return None if value in (None, "unavailable", "unknown") else value

    # Only module 1 and 2 have enabled serial-number entities today (see
    # BATTERY_BMS1_MODULE_1/2_SERIAL_ENTITY's own comment above) — each
    # entry is included only if its serial actually resolved, so a module
    # going offline removes it from the list rather than emitting a
    # fabricated null-serial entry (same "never fabricate" rule as every
    # other field in this module).
    modules = []
    for index, entity_id in (
        (1, BATTERY_BMS1_MODULE_1_SERIAL_ENTITY),
        (2, BATTERY_BMS1_MODULE_2_SERIAL_ENTITY),
    ):
        serial = state_of(entity_id)
        if serial is not None:
            modules.append({"index": index, "serialNumber": serial})

    return {
        "nibe": {
            "manufacturer": NIBE_MANUFACTURER,
            "model": NIBE_MODEL,
            "hwVersion": state_of(NIBE_HW_VERSION_ENTITY),
            "swVersion": state_of(NIBE_SW_VERSION_ENTITY),
        },
        "inverter": {
            "manufacturer": INVERTER_MANUFACTURER,
            # No model string in the HA device registry for this device —
            # left null rather than guessed, see INVERTER_MANUFACTURER's
            # own comment above.
            "model": None,
            "serialNumber": state_of(INVERTER_SERIAL_ENTITY),
            "firmwareVersion": state_of(INVERTER_FIRMWARE_ENTITY),
        },
        "battery": {
            "bmsType": state_of(BATTERY_BMS_TYPE_ENTITY),
            "bms1SerialNumber": state_of(BATTERY_BMS1_SERIAL_ENTITY),
            "bms1MonitoringVersion": state_of(BATTERY_BMS1_MONITORING_VERSION_ENTITY),
            "modules": modules,
            "bmsConnectedStatus": state_of(BATTERY_BMS_CONNECTED_ENTITY),
        },
        "evCharger": {
            "manufacturer": EV_CHARGER_MANUFACTURER,
            "model": EV_CHARGER_MODEL,
            "deviceName": EV_CHARGER_DEVICE_NAME,
            "installedFirmwareVersion": attr_of(
                EV_CHARGER_UPDATE_ENTITY, "installed_version"
            ),
        },
        "vehicle": {
            "manufacturer": VEHICLE_MANUFACTURER,
            "model": VEHICLE_MODEL,
            "vin": state_of(VEHICLE_VIN_ENTITY),
        },
        "perificOne": {
            "manufacturer": PERIFIC_ONE_MANUFACTURER,
            "model": PERIFIC_ONE_MODEL,
            "macAddress": state_of(PERIFIC_ONE_MAC_ENTITY),
            "itemId": state_of(PERIFIC_ONE_ITEM_ID_ENTITY),
        },
    }
