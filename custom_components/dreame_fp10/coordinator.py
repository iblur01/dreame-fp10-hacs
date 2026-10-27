"""Coordinator for Dreame FP10 entities."""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    DreameCloudAPI,
    DreameFP10AuthError,
    DreameFP10ConnectionError,
    DreameFP10EmptyResponseError,
    DreameFP10Error,
    DreameFP10PropertyError,
    PropertyReadResult,
)
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    FP10_MODE_MANUAL,
    FP10_POWER_ON,
    FP10_POWER_STANDBY,
    FP10_SPEED_MAX,
    FP10_SPEED_MIN,
)
from .state import (
    CLOUD_STATUS_AUTH_ERROR,
    CLOUD_STATUS_DEGRADED,
    CLOUD_STATUS_ERROR,
    CLOUD_STATUS_OK,
    INTERNAL_PROPERTY_KEYS,
    TEMPERATURE_STATUS_MISSING,
    TEMPERATURE_STATUS_NOT_REPORTED,
    TEMPERATURE_STATUS_OK,
    TEMPERATURE_STATUS_UNKNOWN,
    MergedState,
    merge_state,
    sanitize_error_message,
)

_LOGGER = logging.getLogger(__name__)

FAILURE_ISSUE_THRESHOLD = 3
FAILURE_HISTORY_SIZE = 20


FP10_PROPERTIES: dict[str, tuple[int, int]] = {
    "power": (2, 1),
    "mode": (2, 3),
    "fan_speed": (2, 4),
    "humidity": (3, 2),
    "temperature": (3, 3),
    "air_quality_level": (3, 4),
    "pm25": (3, 5),
    "tvoc": (3, 6),
    "tvoc_mirror": (3, 9),
    "display_index": (3, 12),
    "display_text": (3, 13),
    "hepa_life": (4, 1),
    "hepa_days": (4, 2),
    "carbon_life": (4, 5),
    "carbon_metric": (4, 6),
    "led_brightness": (6, 6),
    "child_lock": (6, 10),
    "led_breathe": (6, 12),
    "sound": (6, 17),
}

PROPERTY_BY_ID: dict[tuple[int, int], str] = {
    value: key for key, value in FP10_PROPERTIES.items()
}


def device_issue_id(entry_id: str | None, did: str) -> str:
    """Return the repair issue id for a config entry or device."""
    return f"device_unreachable_{entry_id or did}"


def _as_float(value: Any) -> float | None:
    """Return a numeric value as float, or None when it is not numeric."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class PollSnapshot:
    """Diagnostics for one poll of the purifier."""

    started_at: datetime
    duration: float
    success: bool
    requested: int = 0
    received: int = 0
    attempts: int = 0
    missing: tuple[str, ...] = ()
    property_errors: dict[str, int] = field(default_factory=dict)
    raw_values: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error_message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "started_at": self.started_at.isoformat(),
            "duration_ms": round(self.duration * 1000, 1),
            "success": self.success,
            "requested": self.requested,
            "received": self.received,
            "attempts": self.attempts,
            "missing": list(self.missing),
            "property_errors": dict(self.property_errors),
            "raw_values": dict(self.raw_values),
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


@dataclass(slots=True)
class TemperatureDiagnostics:
    """Track why the temperature is valid, missing or reported as zero."""

    status: str = TEMPERATURE_STATUS_UNKNOWN
    raw_value: Any = None
    last_valid_value: float | None = None
    last_valid_at: datetime | None = None
    last_not_reported_at: datetime | None = None
    not_reported_count: int = 0
    missing_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation."""
        return {
            "status": self.status,
            "raw_value": self.raw_value,
            "last_valid_value": self.last_valid_value,
            "last_valid_at": (
                self.last_valid_at.isoformat() if self.last_valid_at else None
            ),
            "last_not_reported_at": (
                self.last_not_reported_at.isoformat()
                if self.last_not_reported_at
                else None
            ),
            "not_reported_count": self.not_reported_count,
            "missing_count": self.missing_count,
        }


@dataclass(slots=True)
class DreameFP10Device:
    """Static FP10 device metadata."""

    did: str
    host: str | None
    name: str
    model: str
    mac: str | None


class DreameFP10Coordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Central polling and command coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: DreameCloudAPI,
        device: DreameFP10Device,
        scan_interval: timedelta = DEFAULT_SCAN_INTERVAL,
        entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}-{device.did}",
            update_interval=scan_interval,
        )
        self.api = api
        self.device = device
        self.entry = entry
        self.entry_id = entry.entry_id if entry is not None else None
        self.last_poll: PollSnapshot | None = None
        self.failure_history: deque[PollSnapshot] = deque(maxlen=FAILURE_HISTORY_SIZE)
        self.consecutive_failures = 0
        self.last_successful_update: datetime | None = None
        self.last_error_type: str | None = None
        self.last_error_message: str | None = None
        self.last_error_at: datetime | None = None
        self.temperature = TemperatureDiagnostics()
        self.property_last_seen: dict[str, datetime] = {}
        self._closing = False

    @classmethod
    def from_entry_data(
        cls,
        hass: HomeAssistant,
        data: dict[str, Any],
        options: dict[str, Any],
        entry: ConfigEntry | None = None,
    ) -> DreameFP10Coordinator:
        """Build a coordinator from config entry data."""
        api = DreameCloudAPI(
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_COUNTRY],
        )
        device = DreameFP10Device(
            did=str(data[CONF_DID]),
            host=data.get(CONF_HOST),
            name=data.get(CONF_DEVICE_NAME, "Dreame FP10"),
            model=data.get(CONF_MODEL, "dreame.airp.u2513"),
            mac=data.get(CONF_MAC),
        )
        interval = timedelta(
            seconds=int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.seconds))
        )
        return cls(hass, api, device, interval, entry)

    @property
    def cloud_status(self) -> str:
        """Summarize cloud connectivity for the diagnostic sensors."""
        if self.last_update_success:
            if (
                self.last_poll
                and self.last_poll.missing
                and self.missing_entity_properties
            ):
                return CLOUD_STATUS_DEGRADED
            return CLOUD_STATUS_OK
        if self.last_error_type == "auth_error":
            return CLOUD_STATUS_AUTH_ERROR
        return CLOUD_STATUS_ERROR

    @property
    def missing_entity_properties(self) -> list[str]:
        """Return missing properties that back a visible entity."""
        if self.last_poll is None or not self.last_poll.success:
            return []
        return [
            key for key in self.last_poll.missing if key not in INTERNAL_PROPERTY_KEYS
        ]

    @property
    def issue_id(self) -> str:
        """Return the repair issue id for this config entry."""
        return device_issue_id(self.entry_id, self.device.did)

    async def _async_setup(self) -> None:
        """Authenticate before the first refresh."""
        try:
            await self.hass.async_add_executor_job(self.api.login)
        except DreameFP10AuthError as ex:
            raise ConfigEntryAuthFailed(sanitize_error_message(ex)) from ex
        except DreameFP10Error as ex:
            # UpdateFailed is converted to ConfigEntryNotReady by
            # async_config_entry_first_refresh, without logging a misleading
            # traceback on older Home Assistant versions.
            raise UpdateFailed(sanitize_error_message(ex)) from ex

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll FP10 state."""
        properties = [
            {"siid": siid, "piid": piid} for siid, piid in FP10_PROPERTIES.values()
        ]
        started_at = dt_util.utcnow()
        started = time.monotonic()

        try:
            result = await self.hass.async_add_executor_job(
                self.api.get_properties_detailed,
                self.device.did,
                properties,
                self.device.host,
            )
        except DreameFP10AuthError as ex:
            self._record_failure(started_at, started, "auth_error", ex)
            raise ConfigEntryAuthFailed(sanitize_error_message(ex)) from ex
        except DreameFP10EmptyResponseError as ex:
            self._record_failure(started_at, started, "empty_response", ex)
            raise UpdateFailed(
                "Dreame Cloud returned an empty property snapshot"
            ) from ex
        except DreameFP10PropertyError as ex:
            self._record_failure(started_at, started, "property_error", ex)
            raise UpdateFailed(sanitize_error_message(ex)) from ex
        except DreameFP10ConnectionError as ex:
            self._record_failure(started_at, started, "connection_error", ex)
            raise UpdateFailed(sanitize_error_message(ex)) from ex
        except Exception as ex:
            _LOGGER.exception("Unexpected error while polling Dreame FP10")
            self._record_failure(started_at, started, "unexpected_error", ex)
            raise UpdateFailed(
                f"Unexpected Dreame FP10 error: {sanitize_error_message(ex)}"
            ) from ex

        merged = merge_state(FP10_PROPERTIES, result.values, self.data)
        self._record_success(merged, result, started_at, started)
        return merged.data

    def _record_success(
        self,
        merged: MergedState,
        result: PropertyReadResult,
        started_at: datetime,
        started: float,
    ) -> None:
        """Store a successful poll and update all diagnostic counters."""
        property_errors = {
            PROPERTY_BY_ID.get(key, f"{key[0]}.{key[1]}"): code
            for key, code in result.errors.items()
        }
        raw_values = {
            key: result.values[prop]
            for key, prop in FP10_PROPERTIES.items()
            if prop in result.values
        }

        self.last_poll = PollSnapshot(
            started_at=started_at,
            duration=time.monotonic() - started,
            success=True,
            requested=result.requested,
            received=len(result.values),
            attempts=result.attempts,
            missing=merged.missing,
            property_errors=property_errors,
            raw_values=raw_values,
        )
        self.last_successful_update = started_at
        self.consecutive_failures = 0

        for key in merged.received:
            self.property_last_seen[key] = started_at

        self._update_temperature(merged, started_at)
        self._delete_offline_issue()

    def _record_failure(
        self,
        started_at: datetime,
        started: float,
        error_type: str,
        error: BaseException,
    ) -> None:
        """Store a failed poll and maintain the offline repair issue."""
        message = sanitize_error_message(error)
        property_errors = {
            PROPERTY_BY_ID.get(key, f"{key[0]}.{key[1]}"): code
            for key, code in getattr(error, "errors", {}).items()
        }
        snapshot = PollSnapshot(
            started_at=started_at,
            duration=time.monotonic() - started,
            success=False,
            requested=getattr(error, "requested", len(FP10_PROPERTIES)),
            attempts=getattr(error, "attempts", 0),
            missing=(),
            property_errors=property_errors,
            error_type=error_type,
            error_message=message,
        )
        self.last_poll = snapshot
        self.failure_history.appendleft(snapshot)
        self.consecutive_failures += 1
        self.last_error_type = error_type
        self.last_error_message = message
        self.last_error_at = started_at
        self.temperature.status = TEMPERATURE_STATUS_UNKNOWN

        if self.consecutive_failures == 1:
            _LOGGER.warning(
                "Dreame FP10 %s poll failed (%s): %s",
                self.device.did,
                error_type,
                message,
            )

        if error_type == "auth_error":
            # Authentication failures are handled by Home Assistant's reauth
            # flow. An old "unreachable" issue would be stale and misleading.
            self._delete_offline_issue()
        elif self.consecutive_failures >= FAILURE_ISSUE_THRESHOLD:
            self._create_offline_issue()

    def _update_temperature(self, merged: MergedState, started_at: datetime) -> None:
        """Track temperature availability for entities and diagnostics."""
        self.temperature.status = merged.temperature_status
        self.temperature.raw_value = merged.raw_temperature

        if merged.temperature_status == TEMPERATURE_STATUS_OK:
            numeric = _as_float(merged.data.get("temperature"))
            if numeric is not None:
                self.temperature.last_valid_value = numeric
                self.temperature.last_valid_at = started_at
        elif merged.temperature_status == TEMPERATURE_STATUS_NOT_REPORTED:
            self.temperature.last_not_reported_at = started_at
            self.temperature.not_reported_count += 1
        elif merged.temperature_status == TEMPERATURE_STATUS_MISSING:
            self.temperature.missing_count += 1

    def _can_create_issue(self) -> bool:
        """Return true while this coordinator is the live entry coordinator."""
        if self._closing:
            return False
        return self.entry is None or self.entry.state is ConfigEntryState.LOADED

    def _create_offline_issue(self) -> None:
        """Create or refresh the offline repair issue."""
        if not self._can_create_issue():
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="device_unreachable",
            translation_placeholders={
                "name": self.device.name,
                "count": str(self.consecutive_failures),
                "error": self.last_error_type or "unknown",
            },
            learn_more_url=(
                "https://github.com/iblur01/dreame-fp10-hacs/blob/main/"
                "docs/DIAGNOSTICS.md"
            ),
        )

    def _delete_offline_issue(self) -> None:
        """Remove the offline repair issue after a successful poll."""
        ir.async_delete_issue(self.hass, DOMAIN, self.issue_id)

    def diagnostics_summary(self) -> dict[str, Any]:
        """Return a JSON-friendly diagnostic snapshot."""
        return {
            "cloud_status": self.cloud_status,
            "last_update_success": self.last_update_success,
            "update_interval_seconds": (
                self.update_interval.total_seconds()
                if self.update_interval is not None
                else None
            ),
            "consecutive_failures": self.consecutive_failures,
            "last_successful_update": (
                self.last_successful_update.isoformat()
                if self.last_successful_update
                else None
            ),
            "last_error": {
                "type": self.last_error_type,
                "message": self.last_error_message,
                "at": self.last_error_at.isoformat() if self.last_error_at else None,
            },
            "temperature": self.temperature.as_dict(),
            "missing_entity_properties": self.missing_entity_properties,
            "last_poll": self.last_poll.as_dict() if self.last_poll else None,
            "failure_history": [
                snapshot.as_dict() for snapshot in self.failure_history
            ],
            "property_last_seen": {
                key: seen.isoformat()
                for key, seen in sorted(self.property_last_seen.items())
            },
            "state": dict(self.data or {}),
        }

    async def async_shutdown(self) -> None:
        """Stop polling and block late diagnostic writes."""
        self._closing = True
        await super().async_shutdown()

    async def async_close(self) -> None:
        """Close the cloud session."""
        self._closing = True
        await self.hass.async_add_executor_job(self.api.close)

    async def _async_call(self, func: Any, *args: Any) -> Any:
        """Run a cloud call and normalize API errors for Home Assistant."""
        try:
            return await self.hass.async_add_executor_job(func, *args)
        except DreameFP10AuthError as ex:
            raise HomeAssistantError(
                "Dreame Cloud authentication failed while sending a command"
            ) from ex
        except DreameFP10Error as ex:
            raise HomeAssistantError(
                f"Dreame FP10 command failed: {sanitize_error_message(ex)}"
            ) from ex

    def _apply_optimistic(self, values: dict[str, Any]) -> None:
        """Apply an optimistic update without clearing a failure state.

        ``async_set_updated_data`` also resets ``last_update_success``. Using it
        after a failed poll would make the entities look healthy even though
        the cloud was never reached, so only the data and listeners are
        updated here.
        """
        self.data = {**(self.data or {}), **values}
        self.async_update_listeners()

    async def async_set_power(self, on: bool) -> None:
        """Set purifier power state."""
        ok = await self._async_call(
            self.api.set_power, self.device.did, on, self.device.host
        )
        if not ok:
            raise HomeAssistantError("Dreame FP10 power command failed")
        # Reflect the change immediately; the cloud read lags the device.
        self._apply_optimistic({"power": FP10_POWER_ON if on else FP10_POWER_STANDBY})

    async def async_set_mode(self, mode: int) -> None:
        """Set FP10 purifier mode."""
        await self.async_set_properties(
            [{"siid": 2, "piid": 3, "value": mode}],
            optimistic_data={"mode": mode},
        )

    async def async_set_fan_speed(self, speed: int) -> None:
        """Set manual fan speed, forcing manual mode first."""
        clamped = max(FP10_SPEED_MIN, min(FP10_SPEED_MAX, speed))
        await self.async_set_properties(
            [
                {"siid": 2, "piid": 3, "value": FP10_MODE_MANUAL},
                {"siid": 2, "piid": 4, "value": clamped},
            ],
            optimistic_data={
                "mode": FP10_MODE_MANUAL,
                "fan_speed": clamped,
            },
        )

    async def async_set_led_brightness(self, brightness: int) -> None:
        """Set LED brightness."""
        value = max(0, min(100, brightness))
        await self.async_set_properties(
            [{"siid": 6, "piid": 6, "value": value}],
            optimistic_data={"led_brightness": value},
        )

    async def async_set_bool(self, key: str, enabled: bool) -> None:
        """Set a boolean vendor option."""
        siid, piid = FP10_PROPERTIES[key]
        await self.async_set_properties(
            [{"siid": siid, "piid": piid, "value": 1 if enabled else 0}],
            optimistic_data={key: 1 if enabled else 0},
        )

    async def async_set_properties(
        self,
        properties: list[dict[str, Any]],
        optimistic_data: dict[str, Any] | None = None,
    ) -> None:
        """Write raw properties and refresh."""
        ok = await self._async_call(
            self.api.set_properties,
            self.device.did,
            properties,
            self.device.host,
        )
        if not ok:
            raise HomeAssistantError("Dreame FP10 property write failed")
        if optimistic_data:
            self._apply_optimistic(optimistic_data)
            return
        await self.async_request_refresh()
