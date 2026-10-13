"""Unit tests for core.hardware_info.fetch_hardware_info.

Same mocking approach as core/nibe/tests/test_live.py: fetch_hardware_info
uses a requests.Session internally (one GET per entity — see the module's
own docstring for why), so these tests mock requests.Session and never
touch a network.
"""

from unittest.mock import Mock, patch

from core.hardware_info import (
    BATTERY_BMS1_MODULE_1_SERIAL_ENTITY,
    BATTERY_BMS1_MODULE_2_SERIAL_ENTITY,
    BATTERY_BMS1_MONITORING_VERSION_ENTITY,
    BATTERY_BMS1_SERIAL_ENTITY,
    BATTERY_BMS_CONNECTED_ENTITY,
    BATTERY_BMS_TYPE_ENTITY,
    EV_CHARGER_UPDATE_ENTITY,
    INVERTER_FIRMWARE_ENTITY,
    INVERTER_SERIAL_ENTITY,
    NIBE_HW_VERSION_ENTITY,
    NIBE_SW_VERSION_ENTITY,
    PERIFIC_ONE_ITEM_ID_ENTITY,
    PERIFIC_ONE_MAC_ENTITY,
    VEHICLE_VIN_ENTITY,
    fetch_hardware_info,
)

BASE_URL = "http://homeassistant.local:8123"
HEADERS = {"Authorization": "Bearer test-token"}


def _state(entity_id: str, state: str, attributes: dict | None = None) -> dict:
    return {"entity_id": entity_id, "state": state, "attributes": attributes or {}}


def _mock_session(states_by_entity: dict[str, dict | None]):
    """Mirrors core/nibe/tests/test_live.py's _mock_session exactly: a
    Mock standing in for requests.Session() whose .get() looks up the
    entity by the URL's trailing segment and returns a canned state dict,
    or an "unavailable" stand-in for any entity the test didn't provide
    (mirroring a genuinely disabled/unavailable entity)."""

    def fake_get(url, headers=None, timeout=None):
        entity_id = url.rsplit("/", 1)[-1]
        response = Mock()
        response.raise_for_status = Mock()
        response.json = Mock(
            return_value=states_by_entity.get(
                entity_id, {"entity_id": entity_id, "state": "unavailable"}
            )
        )
        return response

    session = Mock()
    session.get = Mock(side_effect=fake_get)
    session.close = Mock()
    return session


def test_full_snapshot_maps_every_field():
    states = {
        NIBE_HW_VERSION_ENTITY: _state(NIBE_HW_VERSION_ENTITY, "6"),
        NIBE_SW_VERSION_ENTITY: _state(NIBE_SW_VERSION_ENTITY, "8.11.1"),
        INVERTER_SERIAL_ENTITY: _state(INVERTER_SERIAL_ENTITY, "CZM0D49025"),
        INVERTER_FIRMWARE_ENTITY: _state(INVERTER_FIRMWARE_ENTITY, "DN1.0"),
        BATTERY_BMS_TYPE_ENTITY: _state(BATTERY_BMS_TYPE_ENTITY, "APX HV"),
        BATTERY_BMS1_SERIAL_ENTITY: _state(
            BATTERY_BMS1_SERIAL_ENTITY, "CXM00000231100D4"
        ),
        BATTERY_BMS1_MONITORING_VERSION_ENTITY: _state(
            BATTERY_BMS1_MONITORING_VERSION_ENTITY, "ZECA"
        ),
        BATTERY_BMS1_MODULE_1_SERIAL_ENTITY: _state(
            BATTERY_BMS1_MODULE_1_SERIAL_ENTITY, "VZL0000023110074"
        ),
        BATTERY_BMS1_MODULE_2_SERIAL_ENTITY: _state(
            BATTERY_BMS1_MODULE_2_SERIAL_ENTITY, "VZL0000022460089"
        ),
        BATTERY_BMS_CONNECTED_ENTITY: _state(
            BATTERY_BMS_CONNECTED_ENTITY, "BMS 1 Connected"
        ),
        EV_CHARGER_UPDATE_ENTITY: _state(
            EV_CHARGER_UPDATE_ENTITY, "off", {"installed_version": "3.1.0.3"}
        ),
        VEHICLE_VIN_ENTITY: _state(VEHICLE_VIN_ENTITY, "KNAFD81A1V6183849"),
        PERIFIC_ONE_MAC_ENTITY: _state(PERIFIC_ONE_MAC_ENTITY, "00:70:07:75:6e:8c"),
        PERIFIC_ONE_ITEM_ID_ENTITY: _state(
            PERIFIC_ONE_ITEM_ID_ENTITY, "1785921730582"
        ),
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["nibe"] == {
        "manufacturer": "NIBE Energy Systems",
        "model": "F750 CU 3x400V",
        "hwVersion": "6",
        "swVersion": "8.11.1",
    }
    assert info["inverter"] == {
        "manufacturer": "Growatt New Energy",
        "model": None,
        "serialNumber": "CZM0D49025",
        "firmwareVersion": "DN1.0",
    }
    assert info["battery"] == {
        "bmsType": "APX HV",
        "bms1SerialNumber": "CXM00000231100D4",
        "bms1MonitoringVersion": "ZECA",
        "modules": [
            {"index": 1, "serialNumber": "VZL0000023110074"},
            {"index": 2, "serialNumber": "VZL0000022460089"},
        ],
        "bmsConnectedStatus": "BMS 1 Connected",
    }
    assert info["evCharger"] == {
        "manufacturer": "Zaptec",
        "model": "Zaptec Go2",
        "deviceName": "GPN049831",
        "installedFirmwareVersion": "3.1.0.3",
    }
    assert info["vehicle"] == {
        "manufacturer": "Kia Europe",
        "model": "EV3",
        "vin": "KNAFD81A1V6183849",
    }
    assert info["perificOne"] == {
        "manufacturer": "Perific Technologies AB",
        "model": "Perific Max/One",
        "macAddress": "00:70:07:75:6e:8c",
        "itemId": "1785921730582",
    }


def test_unavailable_entity_reads_as_none_not_fabricated():
    """A disabled/unavailable register must show up as None (the
    frontend's cue to render "Ej tillgänglig"), never as a fabricated
    empty string or placeholder -- same convention as
    core/nibe/live.py's fetch_live_snapshot."""
    states = {
        INVERTER_SERIAL_ENTITY: _state(INVERTER_SERIAL_ENTITY, "CZM0D49025"),
        # NIBE_SW_VERSION_ENTITY deliberately omitted -> "unavailable" from
        # the mock, mirroring the real sensor.software_version_43001
        # confirmed live 2026-10-13.
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["nibe"]["swVersion"] is None
    # Hardcoded facts are unaffected by any entity being unavailable.
    assert info["nibe"]["manufacturer"] == "NIBE Energy Systems"
    assert info["inverter"]["serialNumber"] == "CZM0D49025"


def test_one_product_failing_does_not_blank_the_others():
    """Home Assistant answering for some entities but not others should
    not hide the products that did come back -- only that one product's
    own fields go null."""
    states = {
        VEHICLE_VIN_ENTITY: _state(VEHICLE_VIN_ENTITY, "KNAFD81A1V6183849"),
        PERIFIC_ONE_MAC_ENTITY: _state(PERIFIC_ONE_MAC_ENTITY, "00:70:07:75:6e:8c"),
        # Every Nibe/inverter/battery/charger entity omitted entirely.
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["vehicle"]["vin"] == "KNAFD81A1V6183849"
    assert info["perificOne"]["macAddress"] == "00:70:07:75:6e:8c"
    assert info["nibe"]["hwVersion"] is None
    assert info["nibe"]["swVersion"] is None
    assert info["inverter"]["serialNumber"] is None
    assert info["evCharger"]["installedFirmwareVersion"] is None
    assert info["battery"]["modules"] == []


def test_battery_module_only_included_when_its_serial_resolves():
    """Module 2's serial entity being unavailable should drop it from the
    modules list entirely, never emit a {"index": 2, "serialNumber": None}
    placeholder entry."""
    states = {
        BATTERY_BMS1_MODULE_1_SERIAL_ENTITY: _state(
            BATTERY_BMS1_MODULE_1_SERIAL_ENTITY, "VZL0000023110074"
        ),
        # Module 2 omitted -> unavailable.
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["battery"]["modules"] == [
        {"index": 1, "serialNumber": "VZL0000023110074"}
    ]


def test_zaptec_update_entity_attribute_extraction():
    """installed_version lives in the update.* entity's attributes, not
    its bare state -- confirm attr_of reads it out correctly and that an
    unrelated attribute/state value doesn't leak through as the firmware
    version."""
    states = {
        EV_CHARGER_UPDATE_ENTITY: _state(
            EV_CHARGER_UPDATE_ENTITY,
            "on",
            {"installed_version": "3.1.0.3", "latest_version": "3.2.0.0"},
        ),
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["evCharger"]["installedFirmwareVersion"] == "3.1.0.3"


def test_zaptec_update_entity_unavailable_reads_as_none():
    states = {
        EV_CHARGER_UPDATE_ENTITY: {
            "entity_id": EV_CHARGER_UPDATE_ENTITY,
            "state": "unavailable",
            "attributes": {},
        },
    }

    with patch(
        "core.hardware_info.requests.Session", return_value=_mock_session(states)
    ):
        info = fetch_hardware_info(BASE_URL, HEADERS)

    assert info["evCharger"]["installedFirmwareVersion"] is None
