"""
Main application entry point for the BESS management system.
"""

import json
import os
import threading
import time
import traceback
from collections import deque
from contextlib import asynccontextmanager

import log_config as _  # noqa: F401
import requests

# Import endpoints router
from api import router as endpoints_router
from api_conversion import build_system_settings
from apscheduler.events import EVENT_JOB_MISSED
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from diagnostics_api import router as diagnostics_router
from ev_scheduler_api import router as ev_scheduler_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from governor_api import router as governor_router
from loguru import logger
from nibe_api import router as nibe_router
from perific_api import router as perific_router

# Import BESS system modules
from core.bess import time_utils
from core.bess.battery_system_manager import BatterySystemManager
from core.bess.exceptions import PriceDataUnavailableError
from core.bess.ha_api_controller import HomeAssistantAPIController
from core.bess.settings_store import SettingsStore
from core.governor import peak_governor
from core.nibe import decision as nibe_decision
from core.nibe.controller import (
    DHW_COMFORT_MODE_ECONOMY,
    DHW_COMFORT_MODE_LUXURY,
    NibeController,
)
from core.perific.reader import PerificReader
from core.zaptec import scheduler as ev_scheduler
from core.zaptec.controller import ZaptecController

# Fas 2 stopgap: no Perific settings tab exists yet (that's later UI work,
# same as the checklist-vs-UI tradeoff explained for Zaptec/Nibe), so the
# one entity this app needs is a constant here rather than something read
# from SettingsStore. Confirmed live against Håkan's HA instance 2026-08-29.
PERIFIC_POWER_TOTAL_ENTITY = "sensor.perific_one_perific_perific_one_power_total"

# Fas 3a: same stopgap as Perific above — no Zaptec settings tab yet, so
# these are constants. Confirmed live against Håkan's HA instance 2026-08-29;
# see core/zaptec/__init__.py for what each entity does.
ZAPTEC_AVAILABLE_CURRENT_ENTITY = "number.gpn049831_max_laddstrom"
ZAPTEC_CHARGING_SWITCH_ENTITY = "switch.gpn049831_laddar"

# Fas 5b: same stopgap as above, for the EV's OWN telemetry — a different HA
# integration (kia_uvo) than Zaptec's, so these aren't read through
# ZaptecController (see core/zaptec/scheduler.py's docstring for why).
# Confirmed live against Håkan's HA instance 2026-08-31, the day he switched
# cars — replaces the earlier (now-deleted) Kia Niro entities.
EV_SOC_ENTITY = "sensor.ev3_ev_battery_level"
EV_PLUG_ENTITY = "binary_sensor.ev3_ev_battery_plug"

# Fas 4a: same stopgap as Perific/Zaptec above — no Nibe settings tab yet.
# Confirmed live against Håkan's HA instance (2026-09 conversation), device
# area "Tvättstuga", nibe_heatpump integration via the LilyGO/ESPHome UDP
# gateway. See core/nibe/__init__.py for the full entity catalog.
#
# REVISED 2026-09-22: the heating lever was originally switch.sg_ready_*,
# pivoted away after live investigation found true SG Ready needs two
# physical relay-driven AUX inputs Håkan doesn't have wired — see
# core/nibe/decision.py's MECHANISM CHOICE section for the full story.
# Now targets the curve-offset register directly. Both entities' registry
# entries were disabled_by="integration" by default; enabled + the
# nibe_heatpump config entry reloaded 2026-09-22 to bring them live.
# Still open: no watchdog yet, blocking this running with demo_mode off.
NIBE_HEAT_OFFSET_ENTITY = "number.heat_offset_s1_47011"
NIBE_DHW_COMFORT_MODE_ENTITY = "select.hot_water_comfort_mode_47041"

# Dashboard diagnostics addition (2026-09-03), same stopgap as the constants
# above: read from a live 3-day check-in (see that day's conversation) that
# the inverter's remote-control permission (select.*_vpp_remote_control)
# silently toggled Disabled->Enabled with nothing in the UI reflecting it.
# Growatt/solax_modbus-specific — not wired into the generic platform
# abstraction core.bess uses for SOC/power (those work across platforms;
# this one toggle doesn't have an equivalent on every supported inverter),
# so it's a raw entity read here rather than a new HomeAssistantAPIController
# method. Confirmed live against Håkan's HA instance 2026-09-03.
INVERTER_VPP_REMOTE_CONTROL_ENTITY = (
    "select.garage_solaxgrowatt_inverter_vpp_remote_control"
)

# Rolling window for the battery SOC range diagnostic below — matches the
# 3-day live check-in that prompted adding it, long enough to show a full
# charge/discharge cycle or two without keeping unbounded history in memory.
BATTERY_SOC_RANGE_WINDOW_SECONDS = 3 * 24 * 3600

# Get ingress prefix from environment variable
INGRESS_PREFIX = os.environ.get("INGRESS_PREFIX", "")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifespan manager for FastAPI app."""
    # Startup
    routes = []
    for route in app.routes:
        path = getattr(route, "path", getattr(route, "mount_path", "Unknown path"))
        methods = getattr(route, "methods", None)
        if methods is not None:
            routes.append(f"{path} - {methods}")
        else:
            routes.append(f"{path} - Mounted route or no methods")
    logger.info(f"Registered routes: {routes}")

    yield

    # Shutdown (if needed in the future)


# Create FastAPI app with correct root_path
app = FastAPI(root_path=INGRESS_PREFIX, lifespan=lifespan)


# Add global exception handler to prevent server restarts
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    # Get the full stack trace
    tb_str = traceback.format_exception(type(exc), exc, exc.__traceback__)
    error_msg = "".join(tb_str)

    # Log the full error details
    logger.error(f"Unhandled exception: {exc!s}")
    logger.error(f"Request path: {request.url.path}")
    logger.error(f"Stack trace:\n{error_msg}")

    # Return a 500 response but keep the server running
    return JSONResponse(
        status_code=500,
        content={
            "detail": str(exc),
            "type": str(type(exc).__name__),
            "message": "The server encountered an internal error but is still running.",
        },
    )


# Now that logger patching is complete, log the ingress prefix
logger.info(f"Ingress prefix: {INGRESS_PREFIX}")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for the various paths
static_directory = "/app/frontend"
if os.path.exists(static_directory):
    # Root path assets
    app.mount(
        "/assets", StaticFiles(directory=f"{static_directory}/assets"), name="assets"
    )

# Include the router from endpoints.py
app.include_router(endpoints_router)
# Fas 2: Perific's own small router (core.perific / perific_api.py)
app.include_router(perific_router)
# Fas 3b: the governor's own small router (core.governor / governor_api.py)
app.include_router(governor_router)
# Fas 5c: the EV scheduler's own small router (core.zaptec / ev_scheduler_api.py)
app.include_router(ev_scheduler_router)
# Fas 4a: the Nibe module's own small router (core.nibe / nibe_api.py)
app.include_router(nibe_router)
# 2026-09-03: dashboard-only diagnostics (battery SOC range, inverter
# write-access state) — see diagnostics_api.py's own docstring.
app.include_router(diagnostics_router)


class BESSController:
    def __init__(self):
        """Initialize the BESS Controller."""
        # Startup state: set to True once start() completes.  Until then,
        # API endpoints return an "initializing" response so the UI can show
        # a spinner instead of an error.  startup_status holds a human-readable
        # description of the current step for live progress display.
        self.startup_complete = False
        self.startup_status = ""

        # Environment variables are injected by HA Supervisor (production)
        # or docker-compose (development).

        # Load all settings as early as possible
        options = self._load_options()
        if not options:
            logger.warning("No configuration options found, using defaults")
            options = {}

        # Unified settings store — BESS-managed persistent settings
        self.settings_store = SettingsStore()
        self.settings_store.load(options)

        # Build a merged options view: InfluxDB from options.json, everything
        # else from bess_settings.json (the store takes precedence).
        merged = dict(options)
        for section, value in self.settings_store.data.items():
            merged[section] = value

        # Initialize Home Assistant API Controller with a live settings_store
        # reference, so ha_controller.sensors always reads the active
        # platform's sensors directly — no manually-synced cache (#334).
        growatt_config = merged.get("growatt", {})
        growatt_device_id = growatt_config.get("device_id")
        inverter_config = merged.get("inverter", {})
        huawei_device_id = inverter_config.get("device_id")
        self.ha_controller = self._init_ha_controller(
            self.settings_store,
            growatt_device_id,
            huawei_device_id,
            self.settings_store.get_service_domain(),
            self.settings_store.get_grid_power_polarity(),
            self.settings_store.get_battery_power_polarity(),
        )

        # Fas 2: a second, much smaller HA client for core.perific. Deliberately
        # not reusing self.ha_controller — that class carries a lot of Growatt-
        # specific machinery core.perific has no use for (see reader.py's
        # docstring for the full reasoning). It talks to the same Home
        # Assistant instance, so it resolves its connection details the same
        # way (see _resolve_ha_connection()).
        self.perific_reader = self._init_perific_reader()

        # Fas 3a: same idea as perific_reader above, but this one can also
        # write (see core/zaptec/controller.py's docstring for the full
        # safety reasoning). Its test_mode is wired to the SAME demo_mode
        # flag as ha_controller below — one switch, not two.
        self.zaptec_controller = self._init_zaptec_controller()

        # Fas 4a: same idea as zaptec_controller above, for core.nibe's two
        # comfort levers (curve-offset heating boost + DHW comfort mode —
        # see core/nibe/controller.py's docstring for the full safety
        # reasoning, which mirrors ZaptecController's own).
        # Its test_mode is wired to the SAME demo_mode flag as ha_controller
        # and zaptec_controller below — still one switch, not three.
        self.nibe_controller = self._init_nibe_controller()

        # Fas 3b: last decision peak_governor.decide() made, for the
        # dashboard status card (not built yet — this just holds the value
        # so that increment doesn't also have to touch the polling loop).
        # None until the first poll tick runs, and stays None forever if
        # governor.enabled is False.
        self.governor_last_decision: peak_governor.GovernorDecision | None = None

        # Fas 5b: same idea as governor_last_decision above, for the EV
        # scheduler's dashboard card (Fas 5c, not built yet).
        self.ev_scheduler_last_decision: ev_scheduler.SchedulerDecision | None = None
        # Not user-facing — the plug reading from the previous poll tick,
        # so _poll_ev_charging can pass ev_scheduler.decide() a real
        # was_plug_connected instead of guessing. See that function's own
        # override_should_reset handling for why an unknown prior state
        # (None) is treated the same as "wasn't connected".
        self._ev_scheduler_last_plug_connected: bool | None = None

        # Fas 4a: same idea as governor_last_decision/ev_scheduler_last_decision
        # above, for core.nibe's two levers' dashboard status card. Both None
        # until the first poll tick runs, and stay None forever if the
        # relevant nibe.* enabled flag is False — see _poll_nibe.
        self.nibe_heating_last_decision: nibe_decision.HeatingBoostDecision | None = (
            None
        )
        self.nibe_dhw_last_decision: nibe_decision.DhwLuxuryDecision | None = None

        # Dashboard diagnostics addition (2026-09-03): two independent,
        # always-on, read-only stats — see _poll_diagnostics for why they're
        # grouped into one job, and their own docstrings for what each
        # tracks. Neither gates on a settings.enabled flag (pure reads, no
        # write consequences), so both start populating from the first tick
        # after install, unlike governor_last_decision/ev_scheduler_last_decision.
        self.battery_soc_samples: deque[tuple[float, float]] = deque()
        self.inverter_write_access_state: str | None = None

        # Fas 3b addition (2026-09-03): rolling peak of the same current_kw
        # _poll_peak_governor already reads each tick — context for tuning
        # target_kw before relying on it live. Only ever populated while
        # governor.enabled is True, same "no I/O, no tracking, until
        # explicitly turned on" rule as governor_last_decision.
        self.governor_recent_peak_kw: float | None = None

        # Enable test mode from environment variable OR persisted demo_mode setting.
        # Environment variable takes precedence (for dev/CI use).
        env_test_mode = os.environ.get("HA_TEST_MODE", "false").lower() in (
            "true",
            "1",
            "yes",
        )
        demo_mode = self.settings_store.get_section("demo_mode").get("enabled", False)
        test_mode = env_test_mode or demo_mode
        if test_mode:
            source = "environment" if env_test_mode else "demo_mode setting"
            logger.info(
                "Enabling test mode (%s) - hardware writes will be simulated", source
            )
        self.ha_controller.set_test_mode(test_mode)
        self.zaptec_controller.set_test_mode(test_mode)
        self.nibe_controller.set_test_mode(test_mode)

        # Extract energy provider configuration
        energy_provider_config = merged.get("energy_provider", {})

        # Create Battery System Manager with price provider configuration
        # Let the system manager choose the appropriate price source
        self.system = BatterySystemManager(
            self.ha_controller,
            price_source=None,  # Let system manager auto-select based on config
            energy_provider_config=energy_provider_config,
            addon_options=merged,
        )

        # Set timezone from HA config before any BESS modules use it. This
        # runs after BatterySystemManager construction (above) so that
        # ha_controller.failure_tracker is already wired to a real
        # RuntimeFailureTracker — a final-attempt HA API failure here then
        # surfaces on the existing dashboard banner instead of only being
        # logged (#440).
        try:
            ha_config = self.ha_controller.get_ha_config()
            ha_timezone = ha_config["time_zone"]
            from core.bess.time_utils import set_timezone

            set_timezone(ha_timezone)
            logger.info(f"Timezone set from HA: {ha_timezone}")
        except Exception as e:
            logger.warning(f"Could not read timezone from HA, using default: {e}")

        # Create scheduler with increased misfire grace time to avoid unnecessary warnings
        self.scheduler = BackgroundScheduler(
            {
                "apscheduler.executors.default": {
                    "class": "apscheduler.executors.pool:ThreadPoolExecutor",
                    "max_workers": "20",
                },
                "apscheduler.job_defaults": {
                    "misfire_grace_time": 30  # Allow 30 seconds of misfire before warning
                },
            }
        )

        # Apply all settings to the system immediately (skip on fresh install
        # where the system has no inverter configured — settings will be applied
        # when the user completes the setup wizard).
        if self.system.is_configured:
            self._apply_settings(merged)

        logger.info("BESS Controller initialized with early settings loading")

    def _init_ha_controller(
        self,
        settings_store,
        growatt_device_id=None,
        huawei_device_id=None,
        service_domain=None,
        grid_power_polarity=None,
        battery_power_polarity=None,
    ):
        """Initialize Home Assistant API controller based on environment.

        Args:
            settings_store: Live settings store backing ha_controller.sensors.
            growatt_device_id: Growatt device ID for TOU segment operations.
            huawei_device_id: Huawei device ID for battery operations.
            service_domain: HA integration domain for vendor service calls.
            grid_power_polarity: Sign convention for a platform whose
                import_power/export_power share one signed entity.
            battery_power_polarity: Sign convention for a platform whose
                battery charge/discharge power share one signed entity.
        """
        ha_url, ha_token = self._resolve_ha_connection()

        logger.info(
            "Initializing HA controller with %d sensor configurations",
            len(settings_store.get_active_sensors()),
        )

        return HomeAssistantAPIController(
            ha_url=ha_url,
            token=ha_token,
            settings_store=settings_store,
            growatt_device_id=growatt_device_id,
            huawei_device_id=huawei_device_id,
            service_domain=service_domain,
            grid_power_polarity=grid_power_polarity,
            battery_power_polarity=battery_power_polarity,
        )

    @staticmethod
    def _resolve_ha_connection() -> tuple[str, str]:
        """Work out how to reach Home Assistant's REST API.

        Extracted from the body of _init_ha_controller (Fas 2) so
        _init_perific_reader can resolve the exact same connection details
        without copy-pasting this token lookup a second time — both clients
        talk to the same Home Assistant instance, just for different sensors.

        Returns:
            (ha_url, ha_token)
        """
        ha_token = os.getenv("HASSIO_TOKEN")
        if ha_token:
            ha_url = "http://supervisor/core"
        else:
            ha_token = os.environ.get("HA_TOKEN", "")
            ha_url = os.environ.get("HA_URL", "http://supervisor/core")
        return ha_url, ha_token

    def _init_perific_reader(self) -> PerificReader:
        """Build the Fas 2 Perific client.

        Same connection details as _init_ha_controller, but there is no
        settings-store-backed sensor map to read from yet (see
        PERIFIC_POWER_TOTAL_ENTITY's comment above) — Fas 2/3 UI work adds
        that, matching the Perific/Zaptec/Nibe settings tabs described in
        home-energy-manager-alternative-architecture.md.
        """
        ha_url, ha_token = self._resolve_ha_connection()
        logger.info("Initializing Perific reader for %s", PERIFIC_POWER_TOTAL_ENTITY)
        return PerificReader(
            ha_url=ha_url,
            token=ha_token,
            power_total_entity=PERIFIC_POWER_TOTAL_ENTITY,
        )

    def _init_zaptec_controller(self) -> ZaptecController:
        """Build the Fas 3a Zaptec client.

        Same connection details as _init_ha_controller/_init_perific_reader
        (see _resolve_ha_connection()). Constructed with test_mode=True by
        default (ZaptecController's own default) — the real value is set
        right after, in __init__, at the same place ha_controller's is set,
        from the same demo_mode flag. There is a brief window between this
        call and that line where the object exists but hasn't been told the
        real mode yet; it stays safe throughout because ZaptecController's
        constructor default is also test_mode=True, so it can only ever
        start more cautious than intended, never less.
        """
        ha_url, ha_token = self._resolve_ha_connection()
        logger.info(
            "Initializing Zaptec controller for %s / %s",
            ZAPTEC_AVAILABLE_CURRENT_ENTITY,
            ZAPTEC_CHARGING_SWITCH_ENTITY,
        )
        return ZaptecController(
            ha_url=ha_url,
            token=ha_token,
            available_current_entity=ZAPTEC_AVAILABLE_CURRENT_ENTITY,
            charging_switch_entity=ZAPTEC_CHARGING_SWITCH_ENTITY,
        )

    def _init_nibe_controller(self) -> NibeController:
        """Build the Fas 4a Nibe client.

        Same connection details and same "starts safe by construction"
        argument as _init_zaptec_controller — see that method's docstring.
        """
        ha_url, ha_token = self._resolve_ha_connection()
        logger.info(
            "Initializing Nibe controller for %s / %s",
            NIBE_HEAT_OFFSET_ENTITY,
            NIBE_DHW_COMFORT_MODE_ENTITY,
        )
        return NibeController(
            ha_url=ha_url,
            token=ha_token,
            heat_offset_entity=NIBE_HEAT_OFFSET_ENTITY,
            dhw_comfort_mode_entity=NIBE_DHW_COMFORT_MODE_ENTITY,
        )

    def set_demo_mode(self, enabled: bool) -> None:
        """The one on/off switch for the whole dashboard's hardware writes.

        Håkan's condition for building Fas 3 at all (2026-08-29): there must
        be exactly one clear on/off button for the whole dashboard, not a
        separate one per module. This is that single entry point — it fans
        out to every controller that can write to real hardware:

        - self.system.set_demo_mode() already existed and gates Growatt/
          Huawei writes via ha_controller.
        - self.zaptec_controller.set_test_mode() is new in Fas 3a and gates
          Zaptec's charging-current/on-off writes the same way.
        - self.nibe_controller.set_test_mode() is new in Fas 4a and gates
          the Nibe heat-offset/DHW comfort-mode writes the same way.

        Callers (backend/api.py) should call this instead of reaching into
        bess_controller.system.set_demo_mode() directly, or a future write
        path added here could get missed by callers that only know about
        the old one.
        """
        self.system.set_demo_mode(enabled)
        self.zaptec_controller.set_test_mode(enabled)
        self.nibe_controller.set_test_mode(enabled)

    def _read_raw_entity_state(self, entity_id: str) -> str | None:
        """Read one raw HA entity state, generically.

        ha_controller.get_entity_state_raw() is generic (any known
        entity_id, not Growatt-specific) but — unlike PerificReader's or
        ZaptecController's own _get_raw_state — it re-raises
        requests.RequestException on failure instead of returning None.
        This absorbs that, so callers get the same "no data this cycle,
        not a crash" contract every other polled input already has
        (matches the "unavailable"/"unknown" handling those classes use).

        Originally written for Fas 5b's EV_SOC_ENTITY/EV_PLUG_ENTITY reads
        (hence the generic name despite the narrow original use) and
        renamed 2026-09-03 when the dashboard-diagnostics addition needed
        the exact same "one raw entity, defensively read" behavior for
        INVERTER_VPP_REMOTE_CONTROL_ENTITY — nothing about the
        implementation was EV-specific to begin with.
        """
        try:
            raw = self.ha_controller.get_entity_state_raw(entity_id)
        except requests.RequestException as e:
            logger.warning("Could not read %s: %s", entity_id, e)
            return None
        if raw is None:
            return None
        state = raw.get("state")
        if state in ("unavailable", "unknown", None):
            return None
        return state

    @staticmethod
    def _to_float(raw: str | None) -> float | None:
        """Same defensive parse as ZaptecController._to_float — a state
        string that isn't a real number (or is missing) is "no data this
        cycle", not a crash."""
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    def _poll_ev_charging(self) -> None:
        """Fas 5b: the single 30s tick for both EV-related levers.

        Runs core.zaptec.scheduler.decide() first and applies its verdict
        BEFORE letting peak_governor run at all this tick — see
        scheduler.py's own docstring for why gate-before, not merge:
        peak_governor's auto-resume logic reads only "is the switch off
        and are we under budget", with no idea whether a pause was its own
        or the price/SOC scheduler's. Calling both from one method, in
        this order, on one shared tick is what makes that safe — two
        independently-scheduled 30s jobs could interleave and race.

        ev_scheduler.enabled and governor.enabled are independent toggles;
        this method's own gate only applies when the EV scheduler itself
        is on. peak_governor still runs unmodified (same as before Fas 5b)
        when the EV scheduler is off, and is skipped only when the EV
        scheduler is on and says no (charging_allowed False) or doesn't
        know (None, "no_data" — see SchedulerDecision's own docstring for
        why that must not fall through to a governor read/write either).
        """
        ev_settings = self.settings_store.get_section("ev_scheduler")
        if not ev_settings.get("enabled", False):
            self.ev_scheduler_last_decision = None
            self._poll_peak_governor()
            return

        ev_soc_raw = self._read_raw_entity_state(EV_SOC_ENTITY)
        ev_soc_percent = self._to_float(ev_soc_raw)

        plug_raw = self._read_raw_entity_state(EV_PLUG_ENTITY)
        plug_connected = None if plug_raw is None else plug_raw == "on"

        discharge_power_w = self.ha_controller.get_battery_discharge_power()
        battery_discharging = (
            None if discharge_power_w is None else discharge_power_w > 0
        )

        export_power_w = self.ha_controller.get_export_power()
        solar_surplus_kw = None if export_power_w is None else export_power_w / 1000.0

        spot_price_ore, today_prices_ore = self._read_today_prices_ore()

        decision = ev_scheduler.decide(
            ev_soc_percent=ev_soc_percent,
            plug_connected=plug_connected,
            was_plug_connected=self._ev_scheduler_last_plug_connected,
            override_requested=ev_settings.get("override_requested", False),
            battery_discharging=battery_discharging,
            solar_surplus_kw=solar_surplus_kw,
            spot_price_ore_per_kwh=spot_price_ore,
            today_prices_ore_per_kwh=today_prices_ore,
            soc_cap_percent=ev_settings.get(
                "soc_cap_percent", ev_scheduler.DEFAULT_SOC_CAP_PERCENT
            ),
            low_price_threshold_ore=ev_settings.get(
                "low_price_threshold_ore", ev_scheduler.DEFAULT_LOW_PRICE_THRESHOLD_ORE
            ),
            cheap_price_percentile=ev_settings.get(
                "cheap_price_percentile", ev_scheduler.DEFAULT_CHEAP_PRICE_PERCENTILE
            ),
        )
        self._ev_scheduler_last_plug_connected = plug_connected
        self.ev_scheduler_last_decision = decision

        if decision.override_should_reset and ev_settings.get(
            "override_requested", False
        ):
            self.settings_store.save_section(
                "ev_scheduler", {**ev_settings, "override_requested": False}
            )

        if decision.status == "no_data":
            logger.warning("ev_scheduler: %s", decision.reason)
        else:
            logger.debug("ev_scheduler: %s", decision.reason)

        if decision.charging_allowed is False:
            # The gate is shut — pause and stop. Do NOT call
            # _poll_peak_governor() this tick: its only lever is this same
            # Zaptec switch/current, and running it now is exactly the
            # blind auto-resume this gate exists to prevent.
            self.zaptec_controller.pause_charging()
            return

        if decision.charging_allowed is None:
            # No data — leave charging exactly as it is, including
            # skipping peak_governor, which would otherwise act on this
            # tick's household-power reading without knowing whether the
            # EV scheduler would have allowed that.
            return

        # charging_allowed is True: the gate is open, hand off to the
        # (unchanged) household-power lever.
        self._poll_peak_governor()

    def _poll_diagnostics(self) -> None:
        """Two independent, always-on, read-only dashboard diagnostics.

        Grouped into one 30s job purely to avoid a third scheduler job for
        two near-instant reads — they don't interact, don't gate on each
        other, and neither writes anything. See
        _poll_battery_soc_range/_poll_inverter_write_access for what each
        actually tracks; this method itself has no logic of its own.
        """
        self._poll_battery_soc_range()
        self._poll_inverter_write_access()

    def _poll_battery_soc_range(self) -> None:
        """Track a rolling BATTERY_SOC_RANGE_WINDOW_SECONDS window of
        battery SOC samples, for the dashboard's SOC-range stat.

        Added 2026-09-03 after a live 3-day check-in showed the battery
        cycling repeatedly between its configured floor and a ~60-63%
        ceiling — a pattern invisible from a single point-in-time reading.
        Pure read via the existing platform-generic
        ha_controller.get_battery_soc() (works across inverter platforms,
        unlike the Growatt/solax-specific entity below), so this needs no
        new entity constant and no settings gate: it's exactly the same
        "no data this cycle, not a crash" contract get_battery_soc()
        already gives every other caller — None this tick just means the
        window isn't extended, not an error.
        """
        soc = self.ha_controller.get_battery_soc()
        if soc is None:
            return

        now = time.time()
        self.battery_soc_samples.append((now, soc))

        cutoff = now - BATTERY_SOC_RANGE_WINDOW_SECONDS
        while self.battery_soc_samples and self.battery_soc_samples[0][0] < cutoff:
            self.battery_soc_samples.popleft()

    def _poll_inverter_write_access(self) -> None:
        """Read whether BESS currently has remote-control permission over
        the inverter, for a dashboard indicator.

        Added 2026-09-03 after INVERTER_VPP_REMOTE_CONTROL_ENTITY was
        observed live sitting on "Disabled" for a day, then "Enabled" the
        next, with nothing in the UI showing either state — the DP engine
        can compute a perfect schedule and still have nowhere for it to
        go if this permission happens to be off. Raw state only ("Enabled"
        / "Disabled" / None) — no interpretation here, that belongs to
        whatever renders it.
        """
        self.inverter_write_access_state = self._read_raw_entity_state(
            INVERTER_VPP_REMOTE_CONTROL_ENTITY
        )

    def _read_today_prices_ore(self) -> tuple[float | None, list[float] | None]:
        """Today's buy prices in öre/kWh, and the current one, for the EV
        scheduler. core.bess.price_manager works in SEK/kWh natively (see
        docs/agents/bess-knowledge.md) — Håkan's own rule ("negative/very
        low öre/kWh") and core.zaptec.scheduler's tested contract are both
        in öre, so the *100 conversion belongs at this boundary, not inside
        the pure decision function.

        Returns (None, None) when price data isn't published yet — the
        same "not an error, just no data this cycle" condition
        get_tomorrow_prices() already handles for the next day's prices.
        """
        try:
            today_prices_sek = self.system.price_manager.get_buy_prices()
        except PriceDataUnavailableError:
            return None, None

        today_prices_ore = [p * 100 for p in today_prices_sek]
        period = time_utils.get_current_period_index()
        if 0 <= period < len(today_prices_ore):
            return today_prices_ore[period], today_prices_ore
        return None, today_prices_ore

    def _poll_peak_governor(self) -> None:
        """Fas 3b: reactively cap household power draw by throttling or
        pausing Zaptec's charging current. See
        core/governor/peak_governor.py for the decision logic itself and
        its safety scope (EV lever only — no Nibe lever, no watchdog timer;
        that module's docstring explains why neither is needed yet).

        This is the one place in Fas 3b (now called from _poll_ev_charging,
        Fas 5b — see that method's docstring for why they share one tick
        instead of two independent jobs) that can call ZaptecController's
        write methods automatically. It's safe to do so unconditionally
        here because those methods are already gated by the same
        test_mode flag Demo Mode controls everywhere else (set_demo_mode
        above) — this loop running is exactly the behavior Håkan approved
        conditionally on that gate (2026-08-29/30), not a second, separate
        safety mechanism.

        No-ops entirely (not even a read) when governor.enabled is False,
        which is the shipped default — so installing this code changes
        nothing about anyone's running system until they explicitly turn
        it on in Settings.
        """
        governor_settings = self.settings_store.get_section("governor")
        if not governor_settings.get("enabled", False):
            # Clear any decision from before the governor was switched off —
            # otherwise the status API/dashboard card could keep showing a
            # stale "throttling_ev" from the last tick it was on, which
            # would misrepresent what's actually happening (nothing).
            self.governor_last_decision = None
            # Same reasoning for the recent-peak stat added 2026-09-03: a
            # peak recorded while the governor was on stops being relevant
            # context once it's switched off, so it resets right alongside
            # governor_last_decision rather than lingering as stale context.
            self.governor_recent_peak_kw = None
            return

        target_kw = governor_settings.get("target_kw", peak_governor.DEFAULT_TARGET_KW)
        current_kw = self.perific_reader.get_power_total_kw()
        ev_current_a = self.zaptec_controller.get_available_current_a()
        charging_switch_on = self.zaptec_controller.get_charging_switch_on()

        # 2026-09-03 addition: rolling peak of the same current_kw reading
        # above, for the dashboard — no new HA call, just remembering the
        # max of what this tick already fetched. See the __init__ comment
        # for why this only ever populates while governor.enabled is True.
        if current_kw is not None and (
            self.governor_recent_peak_kw is None
            or current_kw > self.governor_recent_peak_kw
        ):
            self.governor_recent_peak_kw = current_kw

        decision = peak_governor.decide(
            current_kw=current_kw,
            target_kw=target_kw,
            ev_current_a=ev_current_a,
            charging_switch_on=charging_switch_on,
        )

        if decision.ev_current_target_a is not None:
            self.zaptec_controller.set_available_current_a(decision.ev_current_target_a)
        if decision.pause_charging:
            self.zaptec_controller.pause_charging()
        if decision.resume_charging:
            self.zaptec_controller.resume_charging()

        self.governor_last_decision = decision
        if decision.status == "no_data":
            logger.warning("peak_governor: %s", decision.reason)
        elif decision.status == "throttling_ev":
            logger.info("peak_governor: %s", decision.reason)
        else:
            logger.debug("peak_governor: %s", decision.reason)

    def _poll_nibe(self) -> None:
        """Fas 4a: the 30s tick for both Nibe comfort levers (curve-offset
        heating boost + DHW Lyxläge).

        Same cadence as _poll_ev_charging/_poll_peak_governor for
        consistency, even though heat and hot water don't need 30s
        resolution — the price input only changes every 15 minutes.
        Recomputing the same decision a few times between price changes is
        harmless (mirrors peak_governor's own "no hysteresis, on purpose"
        stance: simplicity over an unrequested optimization).

        No-ops entirely (not even a read) when nibe.enabled is False, which
        is the shipped default — so installing this code changes nothing
        about anyone's running system until it's explicitly turned on in
        Settings. The DHW luxury lever has its own nested
        nibe.dhw_luxury_enabled flag (the dashboard switch Håkan asked
        for) — it can be off even while nibe.enabled (the heating-boost
        master switch) is on, and vice versa; decide_dhw_luxury() itself
        treats enabled=False as a pure no-op (see that function's own
        docstring), so it's passed straight through from settings here
        rather than gated a second time in this method.

        On disable, this method deliberately does NOT force either
        register back to a specific state — see NibeController's own
        docstring on the lack of a hardware fail-safe.

        Fas 4b: the watchdog covering "HA/this add-on went down mid-boost"
        is now built (see NibeController.get_heat_offset/
        seconds_since_last_contact and decide_heating_boost's
        watchdog_reset handling) — this method's own job is just to make
        the heartbeat read every tick, unconditionally, so the watchdog
        clock actually advances.
        """
        nibe_settings = self.settings_store.get_section("nibe")
        if not nibe_settings.get("enabled", False):
            self.nibe_heating_last_decision = None
            self.nibe_dhw_last_decision = None
            return

        # Watchdog heartbeat (Fas 4b): always attempted, even on cycles
        # where the value itself isn't otherwise used, so a real pump
        # disconnect is caught regardless of what triggered this tick.
        # This is a pure read — never gated by test_mode/demo_mode, same
        # as every other NibeController read.
        self.nibe_controller.get_heat_offset()
        seconds_since_last_nibe_contact = (
            self.nibe_controller.seconds_since_last_contact()
        )

        governor_settings = self.settings_store.get_section("governor")
        governor_enabled = governor_settings.get("enabled", False)
        target_kw = governor_settings.get(
            "target_kw", peak_governor.DEFAULT_TARGET_KW
        )
        current_kw = self.perific_reader.get_power_total_kw()

        export_power_w = self.ha_controller.get_export_power()
        solar_surplus_kw = (
            None if export_power_w is None else export_power_w / 1000.0
        )

        spot_price_ore, today_prices_ore = self._read_today_prices_ore()

        cheap_price_percentile = nibe_settings.get(
            "cheap_price_percentile", nibe_decision.DEFAULT_CHEAP_PRICE_PERCENTILE
        )
        min_solar_surplus_kw = nibe_settings.get(
            "min_solar_surplus_kw", nibe_decision.DEFAULT_MIN_SOLAR_SURPLUS_KW
        )

        heating_decision = nibe_decision.decide_heating_boost(
            spot_price_ore_per_kwh=spot_price_ore,
            today_prices_ore_per_kwh=today_prices_ore,
            solar_surplus_kw=solar_surplus_kw,
            governor_enabled=governor_enabled,
            current_kw=current_kw,
            target_kw=target_kw,
            seconds_since_last_nibe_contact=seconds_since_last_nibe_contact,
            cheap_price_percentile=cheap_price_percentile,
            min_solar_surplus_kw=min_solar_surplus_kw,
        )
        self.nibe_heating_last_decision = heating_decision
        if heating_decision.heat_offset_c is not None:
            self.nibe_controller.set_heat_offset(heating_decision.heat_offset_c)

        dhw_decision = nibe_decision.decide_dhw_luxury(
            enabled=nibe_settings.get("dhw_luxury_enabled", False),
            spot_price_ore_per_kwh=spot_price_ore,
            today_prices_ore_per_kwh=today_prices_ore,
            solar_surplus_kw=solar_surplus_kw,
            governor_enabled=governor_enabled,
            current_kw=current_kw,
            target_kw=target_kw,
            cheap_price_percentile=cheap_price_percentile,
            min_solar_surplus_kw=min_solar_surplus_kw,
        )
        self.nibe_dhw_last_decision = dhw_decision
        if dhw_decision.comfort_mode == "luxury":
            self.nibe_controller.set_dhw_comfort_mode(DHW_COMFORT_MODE_LUXURY)
        elif dhw_decision.comfort_mode == "economy":
            self.nibe_controller.set_dhw_comfort_mode(DHW_COMFORT_MODE_ECONOMY)
        # comfort_mode is None only when dhw_luxury_enabled is False —
        # deliberately don't touch the register in that case (see
        # decide_dhw_luxury's own docstring).

        if heating_decision.status in ("no_data", "watchdog_reset"):
            logger.warning("nibe heating: %s", heating_decision.reason)
        else:
            logger.debug("nibe heating: %s", heating_decision.reason)
        logger.debug("nibe dhw: %s", dhw_decision.reason)

    def _load_options(self):
        """Load InfluxDB options from /data/options.json.

        In production: /data/options.json provided by Home Assistant add-on system.
        Contains only the influxdb section — all operational settings live in
        /data/bess_settings.json managed by SettingsStore.
        """
        options_json = "/data/options.json"

        if os.path.isfile(options_json):
            try:
                with open(options_json, encoding="utf-8") as f:
                    options = json.load(f)
                    logger.info(f"Loaded options from {options_json}")
            except Exception as e:
                logger.error(f"Error loading options from {options_json}: {e!s}")
                raise RuntimeError(
                    f"Failed to load configuration from {options_json}. " f"Error: {e}"
                ) from e
        else:
            logger.info(
                f"No configuration file at {options_json}, starting with defaults"
            )
            options = {}

        return options

    def refresh_service_domain(self) -> None:
        """Sync the live ha_controller.service_domain from persisted settings.

        Like ha_controller.sensors, this is a plain copy taken at init — an
        inverter platform switch changes which vendor domain the platform
        resolves to, and an explicit inverter.service_domain override
        changes it directly. Call this after any settings mutation that can
        touch the inverter section, or vendor service calls keep targeting
        the previous integration until the next restart.
        """
        self.ha_controller.service_domain = self.settings_store.get_service_domain()

    def refresh_power_polarities(self) -> None:
        """Sync both live signed-sensor polarities from persisted settings.

        Like service_domain, these are plain copies taken at init — an
        inverter platform switch changes which sign conventions (if any)
        apply to a shared signed grid-power sensor (#475/#438) and to a
        shared signed battery-power sensor (#542). Call this after any
        settings mutation that can touch the inverter section.
        """
        self.ha_controller.grid_power_polarity = (
            self.settings_store.get_grid_power_polarity()
        )
        self.ha_controller.battery_power_polarity = (
            self.settings_store.get_battery_power_polarity()
        )

    def apply_discovered_config(
        self,
        sensor_map: dict,
        nordpool_area: str | None = None,
        nordpool_config_entry_id: str | None = None,
        growatt_device_id: str | None = None,
        huawei_device_id: str | None = None,
    ) -> None:
        """Persist discovered config and apply it to the running controller.

        Args:
            sensor_map: dict mapping bess_sensor_key → entity_id
            nordpool_area: Nordpool price area (e.g. "SE4")
            nordpool_config_entry_id: HA config entry ID for Nordpool integration
            growatt_device_id: HA device registry ID for Growatt device
            huawei_device_id: HA device registry ID for Huawei battery device
        """
        self.settings_store.apply_discovered(
            sensor_map=sensor_map,
            nordpool_area=nordpool_area,
            nordpool_config_entry_id=nordpool_config_entry_id,
            growatt_device_id=growatt_device_id,
            huawei_device_id=huawei_device_id,
        )

        # ha_controller.sensors is a live settings_store view (#334) — the
        # settings_store.apply_discovered() call above is already enough for
        # BESS to start using the newly discovered sensors immediately.
        if growatt_device_id:
            self.ha_controller.growatt_device_id = growatt_device_id
        if huawei_device_id:
            self.ha_controller.huawei_device_id = huawei_device_id
        if nordpool_area:
            self.system.price_manager.area = nordpool_area
            self.system.price_manager.clear_cache()
        if nordpool_config_entry_id:
            from core.bess.official_nordpool_source import OfficialNordpoolSource

            price_source = self.system.price_manager.price_source
            if isinstance(price_source, OfficialNordpoolSource):
                price_source.config_entry_id = nordpool_config_entry_id

    def start_scheduler(self) -> None:
        """Start the periodic scheduler if it is not already running.

        Called from ``start()`` during normal startup and from the setup-wizard
        endpoint on a fresh install once the system becomes configured.
        """
        if self.scheduler.running:
            return
        self._init_scheduler_jobs()
        logger.info("Scheduler started")

    def _on_job_missed(self, event) -> None:
        """Surface a coalesced scheduler misfire that would otherwise be silent.

        APScheduler's default coalesce=True drops a missed fire time with no
        log line at all (issue #403) — for update_schedule_quarterly this
        permanently lost a period's actuals with no trace it ever happened.
        Scoped to that job only; other jobs' misfires are not this issue.
        """
        if event.job_id != "update_schedule_quarterly":
            return
        logger.warning(
            f"Scheduled job '{event.job_id}' missed its "
            f"{event.scheduled_run_time:%H:%M} run — previous run still busy, "
            "misfire coalesced away"
        )
        self.system.record_scheduler_misfire(
            job_id=event.job_id,
            scheduled_run_time=event.scheduled_run_time,
        )

    def _init_scheduler_jobs(self):
        """Configure scheduler jobs."""

        # Quarterly schedule update (every 15 minutes: 0, 15, 30, 45)
        def update_schedule_quarterly():
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            self.system.update_battery_schedule(current_period=current_period)

        self.scheduler.add_job(
            update_schedule_quarterly,
            CronTrigger(minute="0,15,30,45"),
            id="update_schedule_quarterly",
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )
        self.scheduler.add_listener(self._on_job_missed, EVENT_JOB_MISSED)

        # Next day preparation (daily at 23:55)
        def prepare_next_day():
            now = time_utils.now()
            current_period = now.hour * 4 + now.minute // 15
            self.system.update_battery_schedule(
                current_period=current_period, prepare_next_day=True
            )

        self.scheduler.add_job(
            prepare_next_day,
            CronTrigger(hour=23, minute=55),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Charging power adjustment (every 5 minutes)
        self.scheduler.add_job(
            self.system.adjust_charging_power,
            CronTrigger(minute="*/5"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Discharge inhibit monitoring (every minute)
        self.scheduler.add_job(
            self.system.apply_discharge_inhibit,
            CronTrigger(minute="*"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Live power-sample buffering for InfluxDB-free runtime gap-fill (#387)
        self.scheduler.add_job(
            self.system.sensor_collector.sample_live_power,
            CronTrigger(minute="*"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Health check refresh (every 5 minutes) — so the dashboard banner
        # self-corrects if sensors recover after a transient failure, instead
        # of only refreshing at startup or on the next settings save.
        self.scheduler.add_job(
            self.system.refresh_health_check,
            CronTrigger(minute="*/5"),
            misfire_grace_time=30,  # Allow 30 seconds of misfire before warning
        )

        # Fas 5b: one shared 30s tick for both EV levers — the price/SOC
        # scheduler (Fas 5a) gates, then (unchanged) peak_governor (Fas 3b)
        # runs. Was two independent jobs through Fas 3b; merged into one so
        # they can't interleave — see _poll_ev_charging's own docstring.
        # Matches Perific One's own ~30s meter refresh, same cadence the
        # original peak_power_governor.py pyscript used. No-ops entirely
        # when both ev_scheduler.enabled and governor.enabled are False
        # (the shipped default for both), so this job runs from the start
        # rather than being started/stopped from the Settings toggles —
        # the toggles just decide whether each tick does anything.
        self.scheduler.add_job(
            self._poll_ev_charging,
            IntervalTrigger(seconds=30),
            id="ev_charging_poll",
            misfire_grace_time=30,
        )

        # Dashboard diagnostics (2026-09-03): battery SOC range + inverter
        # write-access state. Deliberately its own job, not folded into
        # ev_charging_poll above — that job's whole reason for being one
        # merged tick is to stop the EV levers (governor + ev_scheduler)
        # racing over the same Zaptec switch (see _poll_ev_charging's
        # docstring). Neither diagnostic here writes anything or shares
        # state with those levers, so there's no race to avoid and no
        # reason to couple this job's timing to theirs.
        self.scheduler.add_job(
            self._poll_diagnostics,
            IntervalTrigger(seconds=30),
            id="dashboard_diagnostics_poll",
            misfire_grace_time=30,
        )

        # Fas 4a: the Nibe module's own 30s tick — a separate job rather
        # than folded into ev_charging_poll above, since neither of Nibe's
        # two levers touches the Zaptec switch/current those exist to
        # serialize (see _poll_ev_charging's own docstring for why THAT
        # job is merged). No-ops entirely when nibe.enabled is False (the
        # shipped default), same convention as every other gated poll job.
        self.scheduler.add_job(
            self._poll_nibe,
            IntervalTrigger(seconds=30),
            id="nibe_poll",
            misfire_grace_time=30,
        )

        # Give BSM access to the scheduler for one-shot retry jobs
        self.system.set_scheduler(self.scheduler)

        self.scheduler.start()

    def _apply_settings(self, options):
        """Apply all settings from the provided options dictionary.

        This consolidates settings application in one place, ensuring settings
        are applied as early as possible in the initialization process.

        All user-facing settings must be explicitly configured in config.yaml.
        No fallback defaults are provided to ensure deterministic behavior.

        Args:
            options: Dictionary containing all configuration options
        """
        try:
            if not options:
                raise ValueError("Configuration options are required but not provided")

            logger.debug(f"Applying settings: {json.dumps(options, indent=2)}")
            settings = build_system_settings(options)

            logger.debug(f"Formatted settings: {json.dumps(settings, indent=2)}")
            self.system.update_settings(settings)
            logger.info("All settings applied successfully")

        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to apply settings from config.yaml: {e}",
                exc_info=True,
            )
            raise RuntimeError(
                f"Settings application failed - system cannot start safely. "
                f"Check config.yaml for invalid or missing settings. Error: {e}"
            ) from e

    def start(self):
        """Start the scheduler.

        On a fresh install the system is unconfigured — the web server starts
        but scheduling and hardware control are deferred until the user
        completes the setup wizard.
        """
        self.startup_status = "Connecting to Home Assistant..."
        self.system.start(status_callback=self._update_startup_status)

        if not self.system.is_configured:
            logger.info(
                "System unconfigured — scheduler deferred until setup is complete"
            )
            self.startup_complete = True
            return

        self.startup_status = "Running optimization..."
        now = time_utils.now()
        current_period = now.hour * 4 + now.minute // 15
        self.system.update_battery_schedule(current_period=current_period)
        self.startup_status = "Starting scheduler..."
        self.start_scheduler()
        self.startup_complete = True

    def _update_startup_status(self, status: str) -> None:
        """Callback for BatterySystemManager to report startup progress."""
        self.startup_status = status

    def start_in_background(self):
        """Run start() in a background thread so uvicorn can bind immediately.

        On a configured system, start() runs health checks, fetches historical
        data from InfluxDB, and builds the first schedule — this can take
        10-60+ seconds.  Running it in a background thread lets the web server
        start serving immediately.  The dashboard shows an "Initializing"
        spinner until the schedule is ready.
        """

        def _run():
            try:
                self.start()
            except Exception:
                logger.exception("Background startup failed")
                self.startup_complete = True

        thread = threading.Thread(target=_run, name="bess-startup", daemon=True)
        thread.start()


# Global BESS controller instance
bess_controller = BESSController()
bess_controller.start_in_background()

# Get ingress base path, important for Home Assistant ingress
ingress_base_path = os.environ.get("INGRESS_BASE_PATH", "/local_bess_manager/ingress")


# Handle root and ingress paths
# index.html must not be cached — it contains hashed asset references that
# change on every build. Without no-cache, Safari and HA ingress may serve a
# stale index.html that still points to the old JS bundle after an update.
_INDEX_HEADERS = {"Cache-Control": "no-cache, no-store, must-revalidate"}


@app.get("/")
async def root_index():
    logger.info("Root path requested")
    return FileResponse("/app/frontend/index.html", headers=_INDEX_HEADERS)


# All API endpoints are found in api.py and are imported via the router
# The endpoints router is included in the app instance at the top of this file


# SPA catch-all: serve index.html for any path not matched by API or asset routes
@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    return FileResponse("/app/frontend/index.html", headers=_INDEX_HEADERS)
