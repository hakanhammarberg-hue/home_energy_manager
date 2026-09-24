"""PerificReader — reads the live household power draw from Perific One.

This is the whole job, in one sentence: ask Home Assistant "what does
sensor.perific_one_perific_perific_one_power_total say right now?", turn the
answer into a number, and hand that number to whoever asks for it
(core.governor in Fas 3, later possibly core.bess/core.nibe too).

WHY THIS LOOKS THE WAY IT DOES
    BESS Manager already solves exactly this problem for Growatt's sensors —
    see core/bess/ha_api_controller.py's _get_raw_state()/_get_sensor_value().
    Rather than invent a new way to talk to Home Assistant, this class copies
    that same shape on purpose: a small "sensors" dict maps a friendly name
    ("site_power_total") to a real entity_id, an HTTP GET to
    /api/states/{entity_id} fetches the current reading, and "unavailable"/
    "unknown" states are treated as "no data" rather than as an error to
    crash on. Reusing a proven pattern instead of writing a new one is
    itself the point of Tolkning B.

    It is a SEPARATE, smaller class rather than a subclass of
    HomeAssistantAPIController, because that class also carries a lot of
    Growatt/inverter-specific machinery (TOU segments, device IDs, polarity
    settings) that Perific has no use for. Copying the handful of lines this
    actually needs keeps this module readable on its own, without having to
    understand the inverter controller first.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class PerificReader:
    """Reads real-time site power from the Perific One meter via Home Assistant."""

    def __init__(self, ha_url: str, token: str, power_total_entity: str):
        """Set up the reader.

        Args:
            ha_url: Base URL of Home Assistant, e.g. "http://supervisor/core"
                when running as a Home Assistant add-on (same value
                HomeAssistantAPIController uses).
            token: Long-lived access token for the Home Assistant API.
            power_total_entity: The entity_id to read, e.g.
                "sensor.perific_one_perific_perific_one_power_total" — this
                will come from the Perific settings tab once it exists
                (Fas 2 UI work); for now it's passed in directly.
        """
        self.base_url = ha_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.power_total_entity = power_total_entity
        self.session = requests.Session()

    def get_power_total_kw(self) -> float | None:
        """Return current total site power draw in kW, or None if unavailable.

        Positive = importing from the grid (matches how peak_power_governor.py
        already interprets this same sensor).
        """
        raw = self._get_raw_state(self.power_total_entity)
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            logger.warning(
                "Perific power_total sensor %s returned a non-numeric value: %r",
                self.power_total_entity,
                raw,
            )
            return None

    def _get_raw_state(self, entity_id: str) -> str | None:
        """Fetch one entity's raw state string from Home Assistant.

        Returns None (not an exception) for three distinct "no data" cases,
        because a governor polling every 30s needs to treat all three the
        same way — skip this cycle, try again next time — rather than crash:
          1. the HTTP call itself fails (network hiccup, HA restarting)
          2. HA answers but the entity doesn't exist (bad entity_id)
          3. HA answers with the entity, but its state is "unavailable" or
             "unknown" (e.g. Perific's cloud poll hasn't refreshed yet)
        """
        url = f"{self.base_url}/api/states/{entity_id}"
        try:
            response = self.session.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Could not reach Home Assistant for %s: %s", entity_id, e)
            return None

        data = response.json()
        state = data.get("state")

        if state in ("unavailable", "unknown", None):
            logger.debug("%s is currently %s", entity_id, state)
            return None

        return state
