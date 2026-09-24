"""core.nibe.controller — reads AND writes the Nibe F750's space-heating
curve-offset and DHW comfort-mode levers via Home Assistant.

STATUS: Fas 4a (2026-09-20, revised 2026-09-22) — the safety-gated
capability layer, same shape and same safety story as
core.zaptec.controller.ZaptecController (see that module's docstring for
the full "why this is safe to add right now" reasoning; it applies here
unchanged). test_mode defaults True, wired to the SAME demo_mode flag as
Growatt/Zaptec in app.py's BESSController — one button protects all three.

MECHANISM PIVOT (2026-09-22) — READ BEFORE TRUSTING "SG Ready" IN OLD NOTES
    This class originally wrote switch.sg_ready_heating_* as its
    space-heating lever. Live investigation against Håkan's actual F750
    found that switch is a per-function opt-in flag, not an actuator — the
    real SG Ready condition needs two physical relay-driven AUX inputs
    Håkan doesn't have wired (see core/nibe/decision.py's MECHANISM CHOICE
    section for the full story). This class now writes
    number.heat_offset_s1_47011 directly instead — see set_heat_offset()
    below. switch.sg_ready_heating_*/_hot_water_* are no longer touched by
    this module at all; they're left exactly as Håkan's pump defaults them.

THE WRITE-SAFETY CLASSIFICATION (design decision, 2026-09, revised 2026-09-22)
    Borrowed from reviewing github.com/rz4bz4/nibe-lokal's design (a
    Modbus-TCP tool for Nibe S-series, not applicable to the F750's
    hardware, but its write-permission model is sound regardless of
    transport):
    - EVERYDAY  — number.heat_offset_s1_* (space-heating curve offset).
        Automated, written every poll cycle by decide_heating_boost() with
        no extra confirmation, but deliberately range-clamped (see
        set_heat_offset() below) to a small nudge rather than the
        register's full -10..+10 span — it's a real curve register, not a
        purpose-built external-control interface, so this class is more
        conservative with it than SG Ready would have needed to be.
    - GUARDED   — select.hot_water_comfort_mode_* (Luxury/Normal/Economy).
        Still automated (Lyxläge is the whole point of this lever), but
        classified separately because it's a *visible* comfort setting a
        human might also be changing by hand in the pump's own menu at the
        same time — worth distinguishing in logs/diagnostics from the
        curve-offset lever above. Implemented below.
    - BLOCKED   — anything else on the pump: Allow Heating/Allow Additive
        Heating, degree minutes, defrost parameters, climate setpoints.
        Deliberately NOT implemented anywhere in this module, on purpose,
        not by oversight — see core/nibe/__init__.py and decision.py's
        MECHANISM CHOICE section for why (Allow Heating specifically has
        an unconfirmed defrost-interaction risk that curve-offset does
        not share). Adding a write method for any of these needs a
        deliberate, separate design decision, not an incremental
        extension of this class.

NO FAIL-SAFE ON DISCONNECT (read before wiring this into anything unattended)
    Real hardware SG Ready reverts to Normal automatically if its control
    signal is lost — physical dry contacts fail open. This is Modbus over
    Home Assistant: if HA or this add-on stops running, whatever
    number.heat_offset_s1_* was last set to is what the pump keeps using,
    indefinitely (bounded to +MAX_SAFE_HEAT_OFFSET_C by construction, so
    the worst case is a small stuck nudge, not a runaway setting — but
    still not nothing). core.governor's own docstring notes exactly this
    pattern for the now-removed Nibe lever in peak_power_governor.py and
    its timer.peak_governor_safety watchdog — the same watchdog needs to
    exist again before this controller's writes run outside demo mode.
    Built in Fas 4b (2026-09-24): get_heat_offset()/seconds_since_last_contact()
    below track live contact, and core/nibe/decision.py's
    decide_heating_boost() forces the curve offset back to neutral
    (status "watchdog_reset") after DEFAULT_WATCHDOG_TIMEOUT_S (15 min)
    with no confirmed contact while headroom is unknown. This covers "HA
    or this add-on stops running" — it does NOT cover "the pump itself
    loses power/Modbus but this add-on keeps running and keeps reading a
    stale cached state from HA", which would need a staleness check on
    the entity's own last_updated timestamp, not built here.

WHY A SEPARATE CLASS, NOT PART OF ZaptecController
    Different device, different entity domains (number + select here vs.
    number + switch there), different write-safety tiering. Some
    duplication of the "call a service"/"read a raw state" shape versus
    ZaptecController is deliberate — see core/perific/reader.py's docstring
    for the standing rationale: several small, independently-readable
    controller classes beat one shared abstraction that's harder to audit
    for a safety-sensitive path.
"""

import logging
import time

import requests

from core.nibe.decision import MAX_SAFE_HEAT_OFFSET_C

logger = logging.getLogger(__name__)

# Confirmed live 2026-09-22: select.hot_water_comfort_mode_47041's real
# option strings are all-uppercase — "Luxury"/"Economy"/"Normal" (the
# original guesses) never actually matched and every GUARDED-tier write
# this class made would have silently failed at the HA service-call layer
# (select.select_option rejects an option not in the entity's own list).
DHW_COMFORT_MODE_LUXURY = "LUXURY"
DHW_COMFORT_MODE_ECONOMY = "ECONOMY"
DHW_COMFORT_MODE_NORMAL = "NORMAL"


class NibeController:
    """Reads Nibe F750 heat-offset/DHW state and (when not in test mode) controls it."""

    def __init__(
        self,
        ha_url: str,
        token: str,
        heat_offset_entity: str,
        dhw_comfort_mode_entity: str,
        test_mode: bool = True,
    ):
        """Set up the controller.

        Args:
            ha_url: Base URL of Home Assistant.
            token: Long-lived access token.
            heat_offset_entity: EVERYDAY-tier number, e.g.
                "number.heat_offset_s1_47011".
            dhw_comfort_mode_entity: GUARDED-tier select, e.g.
                "select.hot_water_comfort_mode_47041".
            test_mode: Start safe by default, same idiom as
                ZaptecController — a caller must explicitly pass False (or
                call set_test_mode(False) later) to allow real writes.
        """
        self.base_url = ha_url
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.heat_offset_entity = heat_offset_entity
        self.dhw_comfort_mode_entity = dhw_comfort_mode_entity
        self.test_mode = test_mode
        self.session = requests.Session()
        # Fas 4b watchdog: set by get_heat_offset() on every successful read,
        # never by anything else. time.monotonic() rather than time.time()
        # so an NTP clock jump can't produce a bogus timeout or a bogus
        # "just contacted" reading. None until the first successful read
        # since this process started — see decide_heating_boost's own
        # handling of that startup-grace case.
        self.last_contact_monotonic: float | None = None

    def set_test_mode(self, enabled: bool) -> None:
        """Flip the safety gate. See module docstring — driven by Demo Mode."""
        self.test_mode = enabled

    # ------------------------------------------------------------------
    # Reads — always allowed, never gated. Same contract as
    # ZaptecController/PerificReader: None means "no data right now".
    # ------------------------------------------------------------------

    def get_heat_offset(self) -> float | None:
        """Current number.heat_offset_s1_* value, or None if unavailable.

        Fas 4b: this is also the watchdog's own heartbeat — every call that
        successfully parses a value updates last_contact_monotonic,
        regardless of what _poll_nibe does with the returned value. It's
        called every 30s tick unconditionally (see app.py's _poll_nibe) so
        the watchdog stays live even on cycles that otherwise only care
        about headroom/price/solar, not the current offset.
        """
        raw = self._get_raw_state(self.heat_offset_entity)
        if raw is None:
            return None
        try:
            value = float(raw)
        except ValueError:
            return None
        self.last_contact_monotonic = time.monotonic()
        return value

    def seconds_since_last_contact(self) -> float | None:
        """Seconds since get_heat_offset() last confirmed a live read from
        the pump, or None if no read has succeeded yet since this process
        started. See decide_heating_boost's watchdog handling for why a
        fresh-startup None is deliberately not the same thing as a timeout.
        """
        if self.last_contact_monotonic is None:
            return None
        return time.monotonic() - self.last_contact_monotonic

    def get_dhw_comfort_mode(self) -> str | None:
        """Raw select state (e.g. "NORMAL"/"ECONOMY"/"LUXURY"/"SMART CONTROL"),
        or None if unavailable. Confirmed live 2026-09-22."""
        return self._get_raw_state(self.dhw_comfort_mode_entity)

    # ------------------------------------------------------------------
    # Writes — gated by test_mode, deny-by-default, same idiom as
    # ZaptecController._call_service.
    # ------------------------------------------------------------------

    def set_heat_offset(self, offset_c: int) -> bool:
        """EVERYDAY tier. Writes number.heat_offset_s1_*.

        Clamped to +-MAX_SAFE_HEAT_OFFSET_C regardless of what the caller
        passes — defense in depth on top of decision.py already only ever
        producing 0 or +DEFAULT_HEAT_OFFSET_BOOST_C. This is a real pump
        curve register (range -10..+10 on the entity itself); this class
        deliberately never uses more than a small slice of that range.
        """
        clamped = max(-MAX_SAFE_HEAT_OFFSET_C, min(MAX_SAFE_HEAT_OFFSET_C, offset_c))
        if clamped != offset_c:
            logger.warning(
                "set_heat_offset(%s) clamped to %s (safety ceiling +-%s)",
                offset_c,
                clamped,
                MAX_SAFE_HEAT_OFFSET_C,
            )
        return self._call_service(
            domain="number",
            service="set_value",
            entity_id=self.heat_offset_entity,
            data={"value": clamped},
            description=f"set {self.heat_offset_entity} to {clamped}",
        )

    def set_dhw_comfort_mode(self, mode: str) -> bool:
        """GUARDED tier. `mode` should be one of the DHW_COMFORT_MODE_*
        constants above — passed through as-is rather than validated here,
        since the pump's own valid option list is the actual source of
        truth and this class shouldn't hardcode a copy that could drift."""
        return self._call_service(
            domain="select",
            service="select_option",
            entity_id=self.dhw_comfort_mode_entity,
            data={"option": mode},
            description=f"set {self.dhw_comfort_mode_entity} to {mode!r}",
        )

    # ------------------------------------------------------------------
    # Internals — identical shape to ZaptecController's, duplicated on
    # purpose (see core/perific/reader.py's docstring for why).
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
            logger.warning("Nibe write failed (%s): %s", description, e)
            return False

        logger.info("Nibe write sent: %s", description)
        return True

    def _get_raw_state(self, entity_id: str) -> str | None:
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
