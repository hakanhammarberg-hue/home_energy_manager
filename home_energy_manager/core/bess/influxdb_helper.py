"""Provides helper functions to interact with InfluxDB for fetching sensor data.

Talks to InfluxDB via its v1-compatibility login (username + password,
InfluxQL over the /query endpoint) rather than the native v2 API (org +
API token, Flux over /api/v2/query). This is a deliberate choice, not the
"basic"/fallback option: InfluxDB 2.x ships this v1-compatible login
specifically so older clients can authenticate with a plain username and
password instead of juggling org names and long-lived API tokens, and it
is exactly what BESS Manager already uses — successfully, against this
same InfluxDB v2 server — so its already-working credentials can be
copied straight into this app's Configuration tab unchanged (changed
2026-09-30; see config.yaml's influxdb section for the full story of why
the original org+token setup was replaced).

The module includes functionality to parse responses, handle timezones, and process sensor readings.
This module is designed to run within either the Pyscript environment or a standard Python environment.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from core.bess import time_utils

_LOGGER = logging.getLogger(__name__)


PLACEHOLDER_VALUES = {"your_db_username_here", "your_db_password_here"}


def is_influxdb_configured() -> bool:
    """Return True if InfluxDB has real (non-placeholder) credentials configured."""
    try:
        config = get_influxdb_config()
    except (KeyError, FileNotFoundError, json.JSONDecodeError):
        return False

    if (
        not config["url"]
        or not config["username"]
        or not config["password"]
        or not config["bucket"]
    ):
        return False

    if (
        config["username"] in PLACEHOLDER_VALUES
        or config["password"] in PLACEHOLDER_VALUES
    ):
        return False

    return True


def get_influxdb_config():
    """Load InfluxDB config with environment variable precedence.

    Configuration priority (highest to lowest):
    1. Environment variables (HA_DB_URL, HA_DB_BUCKET, HA_DB_USERNAME, HA_DB_PASSWORD)
    2. /data/options.json influxdb section

    This supports both environments:
    - Production: Reads from /data/options.json (configured via HA UI)
    - Development: Environment variables override (from .env, keeps secrets out of git)

    Returns:
        dict: Configuration with url, bucket, username, and password keys

    Raises:
        KeyError: If configuration is incomplete from all sources
        FileNotFoundError: If options.json doesn't exist and env vars not set
    """
    # Check environment variables first (highest priority - development override)
    url = os.getenv("HA_DB_URL")
    bucket = os.getenv("HA_DB_BUCKET")
    username = os.getenv("HA_DB_USERNAME")
    password = os.getenv("HA_DB_PASSWORD")

    # If all environment variables are set, use them
    if url and bucket and username and password:
        _LOGGER.debug("Loaded InfluxDB config from environment variables")
        return {
            "url": url,
            "bucket": bucket,
            "username": username,
            "password": password,
        }

    # Otherwise, read from options.json (production path)
    with open("/data/options.json") as f:
        options = json.load(f)

    influxdb = options["influxdb"]
    _LOGGER.debug("Loaded InfluxDB config from options.json")

    return {
        "url": influxdb.get("url", ""),
        "bucket": influxdb.get("bucket", ""),
        "username": influxdb.get("username", ""),
        "password": influxdb.get("password", ""),
    }


def _split_bucket(bucket: str) -> tuple[str, str]:
    """Split a 'database/retentionPolicy' bucket string into (db, rp).

    Mirrors BESS Manager's own bucket format (e.g. "homeassistant/autogen")
    so the exact same value can be copy-pasted between the two apps'
    Configuration tabs. Defaults the retention policy to InfluxDB's own
    default name, "autogen", when no '/' is present.
    """
    if "/" in bucket:
        db, _, rp = bucket.partition("/")
        return db, rp or "autogen"
    return bucket, "autogen"


def _query_url(base_url: str) -> str:
    """InfluxDB's v1-compatible query endpoint, relative to the configured host root."""
    return f"{base_url.rstrip('/')}/query"


def _run_influxql(config: dict, influxql: str, timeout: int = 10) -> dict:
    """Execute an InfluxQL query against InfluxDB's v1-compatible /query API.

    Auth is HTTP Basic (username/password) — InfluxDB 2.x's built-in
    v1-compatibility login, the same one BESS Manager already uses
    successfully against this exact server.

    Returns:
        {"status": "success", "series": [...]} — series is InfluxDB's raw
        per-series JSON list (each with "tags" and "values"), or
        {"status": "error", "message": str}.
    """
    db, rp = _split_bucket(config["bucket"])

    try:
        response = requests.get(
            _query_url(config["url"]),
            params={"db": db, "rp": rp, "q": influxql, "epoch": "s"},
            auth=(config["username"], config["password"]),
            timeout=timeout,
        )
    except requests.ConnectionError:
        return {"status": "error", "message": f"Cannot reach InfluxDB at {config['url']}"}
    except requests.RequestException as e:
        return {"status": "error", "message": f"Connection error: {e!s}"}

    if response.status_code == 401:
        return {"status": "error", "message": "Wrong InfluxDB username or password"}
    if response.status_code == 404:
        return {
            "status": "error",
            "message": "InfluxDB API endpoint not found — check the URL",
        }
    if response.status_code != 200:
        # The response body carries the real reason (e.g. an unknown
        # database/retention-policy pair) — surface it rather than just the
        # status code.
        body = response.text.strip()
        return {
            "status": "error",
            "message": (
                f"InfluxDB returned HTTP {response.status_code}: {body}"
                if body
                else f"InfluxDB returned HTTP {response.status_code}"
            ),
        }

    try:
        payload = response.json()
    except ValueError:
        return {"status": "error", "message": "InfluxDB response was not valid JSON"}

    results = payload.get("results", [])
    if not results:
        return {"status": "success", "series": []}

    result = results[0]
    if "error" in result:
        return {"status": "error", "message": f"InfluxDB query error: {result['error']}"}

    return {"status": "success", "series": result.get("series", []) or []}


def _flatten_series(series_list: list[dict]) -> list[tuple[str, int, float]]:
    """Flatten InfluxQL JSON series (grouped by the 'entity_id' tag) into flat rows.

    Each series corresponds to one GROUP BY "entity_id" group; its "values"
    are [epoch_seconds, value] pairs (in query order, ascending time unless
    the query says otherwise). Rows with a null value (InfluxDB's gap
    representation) are dropped.
    """
    rows: list[tuple[str, int, float]] = []
    for series in series_list:
        entity_id = series.get("tags", {}).get("entity_id")
        if not entity_id:
            continue
        for row in series.get("values") or []:
            if len(row) < 2 or row[1] is None:
                continue
            try:
                rows.append((entity_id, int(row[0]), float(row[1])))
            except (TypeError, ValueError):
                continue
    return rows


def _entity_filter_clause(sensors_list) -> str:
    return " OR ".join(f'"entity_id" = \'{sensor}\'' for sensor in sensors_list)


def test_influxdb_connection() -> dict:
    """Test InfluxDB connectivity and bucket configuration.

    Runs a trivial metadata query (no sensor filtering), so the result is
    independent of which sensors are configured.

    Returns:
        dict: {"status": "ok" | "misconfigured" | "error", "message": str}
    """
    config = get_influxdb_config()
    if not all(config.values()):
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    db, rp = _split_bucket(config["bucket"])
    result = _run_influxql(config, "SHOW MEASUREMENTS LIMIT 1", timeout=10)

    if result["status"] == "error":
        return result

    if not result["series"]:
        return {
            "status": "misconfigured",
            "message": (
                f"InfluxDB responded but returned no measurements. "
                f"Current database: '{db}', retention policy: '{rp}'. "
                f"Verify the bucket field matches an existing InfluxDB "
                f"database/retention-policy pair (e.g. 'homeassistant/autogen', "
                f"the same format BESS Manager uses) and that the user has "
                f"read access to it."
            ),
        }

    return {"status": "ok", "message": "InfluxDB connection successful"}


def get_sensor_data(sensors_list, start_time=None, stop_time=None) -> dict:
    """Get sensor data with configurable time range.

    Args:
        sensors_list: List of sensor names to query
        start_time: Start time for the query (defaults to 24h before stop_time)
        stop_time: End time for the query (defaults to now)

    Returns:
        dict: Query results with status and data
    """
    # Set up timezone
    local_tz = time_utils.TIMEZONE

    # Determine stop time
    if stop_time is None:
        stop_time = datetime.now(local_tz)
    elif stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=local_tz)

    # Determine start time - default to 24h before stop time
    if start_time is None:
        start_time = stop_time - timedelta(hours=24)
        _LOGGER.debug("Using default 24-hour window")
    elif start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=local_tz)

    # Get configuration
    config = get_influxdb_config()

    # Validate required configuration
    if not all(config.values()):
        _LOGGER.error(
            "InfluxDB configuration is incomplete. URL: %s, Bucket: %s",
            config.get("url"),
            config.get("bucket"),
        )
        return {"status": "error", "message": "Incomplete InfluxDB configuration"}

    # Format times for InfluxDB query
    start_str = start_time.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_str = stop_time.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    influxql = (
        'SELECT last("value") FROM /^.*$/ '
        f"WHERE ({_entity_filter_clause(sensors_list)}) "
        f"AND time >= '{start_str}' AND time <= '{end_str}' "
        'GROUP BY "entity_id"'
    )

    result = _run_influxql(config, influxql, timeout=10)
    if result["status"] == "error":
        _LOGGER.error("Error from InfluxDB: %s", result["message"])
        return result

    rows = _flatten_series(result["series"])
    if not rows:
        _LOGGER.warning("No data found for the requested sensors")
        return {"status": "error", "message": "No data found"}

    # last() + GROUP BY yields exactly one row per matched entity_id.
    readings = {f"sensor.{entity_id}": value for entity_id, _epoch, value in rows}

    return {"status": "success", "data": readings, "has_valid_csv": True}


def get_sensor_data_batch(sensors_list, target_date) -> dict:
    """Fetch all 96 periods of sensor data for a given date in a single query.

    This is dramatically faster than making 96+ individual queries.

    Args:
        sensors_list: List of sensor names to query
        target_date: Date to fetch data for (datetime.date or datetime)

    Returns:
        dict: {
            "status": "success" or "error",
            "message": error message if status is "error",
            "data": {
                0: {sensor1: value, sensor2: value, ...},  # Period 0 (00:00-00:14)
                1: {...},  # Period 1 (00:15-00:29)
                ...
                95: {...}  # Period 95 (23:45-23:59)
            }
        }
    """
    local_tz = time_utils.TIMEZONE

    # Convert target_date to datetime if it's a date
    if isinstance(target_date, datetime):
        target_date = target_date.date()

    # Create start and end times for the full day
    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_datetime = datetime.combine(target_date, datetime.max.time()).replace(
        tzinfo=local_tz
    )

    if not sensors_list:
        _LOGGER.warning("No sensors configured — skipping InfluxDB query")
        return {"status": "error", "message": "No sensors configured"}

    if not is_influxdb_configured():
        _LOGGER.debug("InfluxDB is not configured — skipping query")
        return {"status": "error", "message": "InfluxDB not configured"}

    config = get_influxdb_config()

    start_str = start_datetime.astimezone(ZoneInfo("UTC")).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end_str = end_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    influxql = (
        'SELECT "value" FROM /^.*$/ '
        f"WHERE ({_entity_filter_clause(sensors_list)}) "
        f"AND time >= '{start_str}' AND time <= '{end_str}' "
        'GROUP BY "entity_id"'
    )

    try:
        _LOGGER.info(
            "Batch fetching sensor data for %s (%d sensors, 96 periods)",
            target_date.strftime("%Y-%m-%d"),
            len(sensors_list),
        )
        _LOGGER.info("Querying sensors: %s", sensors_list)

        result = _run_influxql(config, influxql, timeout=30)
        if result["status"] == "error":
            _LOGGER.error("Error from InfluxDB: %s", result["message"])
            return result

        rows = _flatten_series(result["series"])
        _LOGGER.info("InfluxDB returned %d data point(s)", len(rows))

        measurements: dict[str, int] = {}
        for entity_id, _epoch, _value in rows:
            key = f"sensor.{entity_id}"
            measurements[key] = measurements.get(key, 0) + 1
        _LOGGER.info("Sensor counts in response: %s", measurements)
        if not measurements:
            _LOGGER.warning("Zero sensors found in InfluxDB response for %s", target_date)

        sensor_data: dict[str, list[tuple[datetime, float]]] = {}
        for entity_id, epoch_s, value in rows:
            ts_local = datetime.fromtimestamp(epoch_s, tz=ZoneInfo("UTC")).astimezone(
                local_tz
            )
            sensor_data.setdefault(f"sensor.{entity_id}", []).append((ts_local, value))
        for key in sensor_data:
            sensor_data[key].sort(key=lambda point: point[0])

        period_data = _bucket_last_value_per_period(
            sensor_data, sensors_list, target_date, local_tz
        )

        _LOGGER.info("Batch fetch complete: got data for %d periods", len(period_data))

        if period_data:
            periods = sorted(period_data.keys())
            _LOGGER.info(
                "Periods found in batch: %s...%s (total: %d)",
                periods[:5] if len(periods) > 5 else periods,
                periods[-5:] if len(periods) > 5 else [],
                len(periods),
            )
            for p in periods[:3]:
                sensors = list(period_data[p].keys())
                _LOGGER.info(
                    "Period %d has %d sensors: %s",
                    p,
                    len(sensors),
                    sensors[:5] if len(sensors) > 5 else sensors,
                )

        return {"status": "success", "data": period_data}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error in batch fetch: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _bucket_last_value_per_period(
    sensor_data: dict[str, list[tuple[datetime, float]]],
    sensors_list,
    target_date,
    local_tz,
) -> dict[int, dict[str, float]]:
    """Group raw (timestamp, value) points into the 96 quarterly periods of a day.

    For each period, takes the last value at or before that period's end —
    for sparse cumulative counters this mimics InfluxQL's own last()
    semantics applied at each period boundary. For sensors with no point on
    or before day-start, fetches one initial value from just before the day
    (single extra batched query) so the very first periods aren't left
    without a starting reading.
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )

    sensors_needing_initial_values = []
    for sensor_name in sensors_list:
        prefixed_name = f"sensor.{sensor_name}"
        needs_initial_value = False

        if prefixed_name not in sensor_data or not sensor_data[prefixed_name]:
            needs_initial_value = True
            _LOGGER.debug(
                "Sensor %s has no data for %s, will fetch initial value",
                sensor_name,
                target_date,
            )
        else:
            first_timestamp = sensor_data[prefixed_name][0][0]
            if first_timestamp > day_start:
                needs_initial_value = True
                _LOGGER.debug(
                    "Sensor %s first data at %s (after day start), will fetch initial value",
                    sensor_name,
                    first_timestamp,
                )

        if needs_initial_value:
            sensors_needing_initial_values.append(sensor_name)

    if sensors_needing_initial_values:
        _LOGGER.info(
            "Batch fetching initial values for %d sensors",
            len(sensors_needing_initial_values),
        )
        result = get_sensor_data(
            sensors_needing_initial_values, stop_time=day_start - timedelta(seconds=1)
        )

        if result.get("status") == "success" and result.get("data"):
            for sensor_name in sensors_needing_initial_values:
                prefixed_name = f"sensor.{sensor_name}"
                sensor_value = result["data"].get(prefixed_name) or result["data"].get(
                    sensor_name
                )
                if sensor_value is not None:
                    _LOGGER.debug(
                        "Found initial value for %s: %.2f (from before %s)",
                        sensor_name,
                        sensor_value,
                        target_date,
                    )
                    initial_datapoint = (day_start - timedelta(seconds=1), sensor_value)
                    if prefixed_name in sensor_data:
                        sensor_data[prefixed_name].insert(0, initial_datapoint)
                    else:
                        sensor_data[prefixed_name] = [initial_datapoint]

    period_data: dict[int, dict[str, float]] = {}
    for period in range(96):
        period_end = day_start + timedelta(minutes=(period + 1) * 15 - 1, seconds=59)
        period_data[period] = {}

        for sensor_name, data_points in sensor_data.items():
            last_value = None
            for timestamp, value in data_points:
                if timestamp <= period_end:
                    last_value = value
                else:
                    break  # Data is sorted, no need to continue
            if last_value is not None:
                period_data[period][sensor_name] = last_value

    period_data = {p: data for p, data in period_data.items() if data}

    _LOGGER.debug(
        "Bucketed %d sensors with data for %d periods", len(sensor_data), len(period_data)
    )

    return period_data


def get_power_sensor_data_batch(power_sensors: list[str], target_date) -> dict:
    """Fetch average power (W) per period and convert to energy (kWh).

    Power sensors report instantaneous wattage every ~5 minutes. By averaging
    all readings within each 15-minute period and converting W -> kWh, we get
    much higher resolution than cumulative energy sensors (which only increment
    in 0.1 kWh steps).

    Args:
        power_sensors: List of power sensor entity IDs (without 'sensor.' prefix)
        target_date: Date to fetch data for (datetime.date or datetime)

    Returns:
        dict: {
            "status": "success" or "error",
            "message": error message if status is "error",
            "data": {
                0: {sensor1: avg_kwh, sensor2: avg_kwh, ...},
                ...
                95: {...}
            }
        }
    """
    local_tz = time_utils.TIMEZONE

    if isinstance(target_date, datetime):
        target_date = target_date.date()

    start_datetime = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )
    end_datetime = datetime.combine(target_date, datetime.max.time()).replace(
        tzinfo=local_tz
    )

    if not is_influxdb_configured():
        _LOGGER.debug("InfluxDB is not configured — skipping query")
        return {"status": "error", "message": "InfluxDB not configured"}

    config = get_influxdb_config()

    start_str = start_datetime.astimezone(ZoneInfo("UTC")).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    end_str = end_datetime.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    influxql = (
        'SELECT "value" FROM /^.*$/ '
        f"WHERE ({_entity_filter_clause(power_sensors)}) "
        f"AND time >= '{start_str}' AND time <= '{end_str}' "
        'GROUP BY "entity_id"'
    )

    try:
        _LOGGER.info(
            "Batch fetching power sensor data for %s (%d sensors)",
            target_date.strftime("%Y-%m-%d"),
            len(power_sensors),
        )

        result = _run_influxql(config, influxql, timeout=30)
        if result["status"] == "error":
            _LOGGER.error("Error from InfluxDB: %s", result["message"])
            return result

        rows = _flatten_series(result["series"])
        period_data = _bucket_mean_power_per_period(rows, target_date, local_tz)

        _LOGGER.info(
            "Power sensor batch complete: got data for %d periods", len(period_data)
        )

        return {"status": "success", "data": period_data}

    except requests.RequestException as e:
        _LOGGER.error("Error connecting to InfluxDB for power sensors: %s", str(e))
        return {"status": "error", "message": f"Connection error: {e!s}"}
    except Exception as e:
        _LOGGER.error("Unexpected error in power sensor batch fetch: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {e!s}"}


def _bucket_mean_power_per_period(
    rows: list[tuple[str, int, float]], target_date, local_tz
) -> dict[int, dict[str, float]]:
    """Average power (W) readings within each 15-minute period, convert to kWh.

    kWh = mean_watts * (15/60) / 1000
    """
    day_start = datetime.combine(target_date, datetime.min.time()).replace(
        tzinfo=local_tz
    )

    sensor_period_readings: dict[str, dict[int, list[float]]] = {}

    for entity_id, epoch_s, value in rows:
        # Skip clearly bogus values (e.g. the output_power 429496663.7 overflow)
        if abs(value) > 100000:
            continue

        timestamp_local = datetime.fromtimestamp(epoch_s, tz=ZoneInfo("UTC")).astimezone(
            local_tz
        )
        seconds_since_start = (timestamp_local - day_start).total_seconds()
        if seconds_since_start < 0 or seconds_since_start >= 86400:
            continue
        period = int(seconds_since_start // 900)  # 900 seconds = 15 minutes

        sensor_name = f"sensor.{entity_id}"
        sensor_period_readings.setdefault(sensor_name, {}).setdefault(
            period, []
        ).append(value)

    period_data: dict[int, dict[str, float]] = {}
    for sensor_name, periods in sensor_period_readings.items():
        for period, values in periods.items():
            mean_watts = sum(values) / len(values)
            kwh = mean_watts * 0.25 / 1000.0  # W * hours / 1000 = kWh
            period_data.setdefault(period, {})[sensor_name] = kwh

    _LOGGER.debug(
        "Parsed power data: %d sensors across %d periods",
        len(sensor_period_readings),
        len(period_data),
    )

    return period_data
