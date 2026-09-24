"""ZaptecController — reads AND writes Zaptec Go 2 charging state via Home Assistant.

STATUS: Fas 3a — the safety-gated capability layer only. No governor logic
lives here yet (that's Fas 3b, built once this is reviewed): nothing in the
app calls set_available_current_a() or pause_charging() automatically. This
module can be wired in and tested without any risk of it doing anything
to the real charger by itself.

WHY THIS IS SAFE TO ADD RIGHT NOW
    Håkan's condition for continuing to Fas 3 (2026-08-29): building this
    must not risk the EV charging session or Growatt currently in progress,
    and there must be one clear on/off switch for the whole thing. Both are
    satisfied by copying BESS's own existing safety mechanism instead of
    inventing a new one:

    core/bess/ha_api_controller.py already has a `test_mode` flag that, when
    on, intercepts every service call ("would call X, not calling it") and
    a "Demo Mode" toggle already wired end-to-end (Settings page banner,
    /api/settings, BatterySystemManager.set_demo_mode()) that flips it. This
    class copies that exact same test_mode idiom — deny-by-default, log
    instead of act — for Zaptec's two write operations. app.py wires this
    controller's test_mode to the SAME demo_mode flag as the Growatt
    controller (see BESSController.set_demo_mode), so there is exactly one
    button, not two: flipping "Demo Mode" in Settings protects Growatt AND
    Zaptec together.

    On top of that, this module doesn't call its own write methods from
    anywhere yet — there is no scheduler job, no polling loop, nothing
    invoking set_available_current_a() or pause_charging() automatically.
    Fas 3a is the capability existing and being provably inert; Fas 3b is
    the governor loop that actually decides when to use it.

WHY A SEPARATE CLASS, NOT PART OF PerificReader OR HomeAssistantAPIController
    PerificReader is read-only by nature (see its own docstring — the
    integration it talks to has no write capability at all). Zaptec is
    different: custom-components/zaptec supports real writes, so this needs
    its own write path with its own safety gate. Not folded into
    HomeAssistantAPIController for the same reason PerificReader wasn't:
    that class carries a lot of Growatt-specific machinery this has no use
    for. Some duplication of the "read a sensor" shape versus PerificReader
    is deliberate — two small, independently-readable classes beat one
    shared abstraction that's harder to audit for a safety-sensitive path.

Bekräftade riktiga entiteter (2026-08-29):
    number.gpn049831_max_laddstrom   — skrivbar, sätter tillgänglig laddström
    number.gpn049831_min_laddstrom   — golv, 6.0A (matchar ZAPTEC_FLOOR_CURRENT)
    switch.gpn049831_laddar          — på/av
    Zaptecs verkliga installationskapacitet är 16A/3-fas = 11kW (bekräftat av
    Håkan) — ZAPTEC_NORMAL_MAX_CURRENT nedan är alltså 16, inte de 32 som
    peak_power_governor.py ursprungligen antog.
"""

import logging

import requests

logger = logging.getLogger(__name__)

ZAPTEC_NORMAL_MAX_CURRENT = (
    16  # amps — confirmed real installation limit (11kW/3-phase)
)
ZAPTEC_FLOOR_CURRENT = 6  # amps — matches number.gpn049831_min_laddstrom


class ZaptecController:
    """Reads Zaptec's charging state and (when not in test mode) controls it."""

    def __init__(
        self,
        ha_url: str,
        token: str,
        available_current_entity: str,
        charging_switch_entity: str,
        test_mode: bool = True,
    ):
        """Set up the controller.

        Args:
            ha_url: Base URL of Home Assistant.
            token: Long-lived access token.
            available_current_entity: The writable "max charging current"
                number entity, e.g. "number.gpn049831_max_laddstrom".
            charging_switch_entity: The on/off switch entity, e.g.
                "switch.gpn049831_laddar".
            test_mode: Start safe by default — a caller must explicitly pass
                False (or call set_test_mode(False) later) to allow real
                writes. This is independent of, but meant to be driven by,
                the same Demo Mode flag Growatt already uses (see app.py).
        """
        self.base_url = ha_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.available_current_entity = available_current_entity
        self.charging_switch_entity = charging_switch_entity
        self.test_mode = test_mode
        self.session = requests.Session()

    def set_test_mode(self, enabled: bool) -> None:
        """Flip the safety gate. See module docstring — driven by Demo Mode."""
        self.test_mode = enabled

    # ------------------------------------------------------------------
    # Reads — always allowed, never gated. Matches PerificReader's contract:
    # None means "no data right now", not an error to raise on.
    # ------------------------------------------------------------------

    def get_available_current_a(self) -> float | None:
        """Current value of the writable max-current number entity."""
        raw = self._get_raw_state(self.available_current_entity)
        return self._to_float(raw)

    def get_charging_switch_on(self) -> bool | None:
        """True/False, or None if the switch entity is unavailable."""
        raw = self._get_raw_state(self.charging_switch_entity)
        if raw is None:
            return None
        return raw == "on"

    # ------------------------------------------------------------------
    # Writes — gated by test_mode, deny-by-default, same idiom as
    # HomeAssistantAPIController._call_service.
    # ------------------------------------------------------------------

    def set_available_current_a(self, amps: float) -> bool:
        """Set Zaptec's available charging current.

        Returns True if a real write was sent, False if test_mode blocked it
        (or the write itself failed) — callers that care about "did this
        actually happen" can check the return value; the log line is there
        either way.
        """
        return self._call_service(
            domain="number",
            service="set_value",
            entity_id=self.available_current_entity,
            data={"value": amps},
            description=f"set {self.available_current_entity} to {amps}A",
        )

    def pause_charging(self) -> bool:
        """Turn the charging switch off."""
        return self._call_service(
            domain="switch",
            service="turn_off",
            entity_id=self.charging_switch_entity,
            data={},
            description=f"turn off {self.charging_switch_entity}",
        )

    def resume_charging(self) -> bool:
        """Turn the charging switch on."""
        return self._call_service(
            domain="switch",
            service="turn_on",
            entity_id=self.charging_switch_entity,
            data={},
            description=f"turn on {self.charging_switch_entity}",
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _call_service(
        self, domain: str, service: str, entity_id: str, data: dict, description: str
    ) -> bool:
        if self.test_mode:
            logger.info("[TEST MODE] Would %s (no request sent)", description)
            return False

        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = {"entity_id": entity_id, **data}
        try:
            response = self.session.post(
                url, headers=self.headers, json=payload, timeout=10
            )
            response.raise_for_status()
        except requests.RequestException as e:
            logger.warning("Zaptec write failed (%s): %s", description, e)
            return False

        logger.info("Zaptec write sent: %s", description)
        return True

    def _get_raw_state(self, entity_id: str) -> str | None:
        """Same shape as PerificReader._get_raw_state — see that class for
        why 'unavailable'/'unknown'/network failure all collapse to None."""
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
            return None
        return state

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None
