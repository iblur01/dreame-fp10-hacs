"""Coordinator for Dreame FP10 entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DreameCloudAPI, DreameFP10Error
from .const import (
    CONF_COUNTRY,
    CONF_DID,
    CONF_DEVICE_NAME,
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

_LOGGER = logging.getLogger(__name__)


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
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}-{device.did}",
            update_interval=scan_interval,
        )
        self.api = api
        self.device = device

    @classmethod
    def from_entry_data(
        cls,
        hass: HomeAssistant,
        data: dict[str, Any],
        options: dict[str, Any],
    ) -> "DreameFP10Coordinator":
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
        return cls(hass, api, device, interval)

    async def _async_setup(self) -> None:
        """Authenticate before the first refresh."""
        await self.hass.async_add_executor_job(self.api.login)

    async def _async_update_data(self) -> dict[str, Any]:
        """Poll FP10 state."""
        properties = [
            {"siid": siid, "piid": piid} for siid, piid in FP10_PROPERTIES.values()
        ]
        try:
            raw_values = await self.hass.async_add_executor_job(
                self.api.get_properties,
                self.device.did,
                properties,
                self.device.host,
            )
        except DreameFP10Error as ex:
            raise UpdateFailed(str(ex)) from ex

        # The cloud occasionally drops a property from an otherwise complete
        # response. Carry the last known value forward instead of blanking the
        # entity, so a single flaky poll does not flip sensors to unavailable.
        previous = self.data or {}
        data: dict[str, Any] = {}
        for key, prop in FP10_PROPERTIES.items():
            if prop in raw_values:
                data[key] = raw_values[prop]
            else:
                data[key] = previous.get(key)
        return data

    async def async_set_power(self, on: bool) -> None:
        """Set purifier power state."""
        ok = await self.hass.async_add_executor_job(
            self.api.set_power, self.device.did, on, self.device.host
        )
        if not ok:
            raise HomeAssistantError("Dreame FP10 power command failed")
        # Reflect the change immediately; the cloud read lags the device.
        self.async_set_updated_data(
            {
                **(self.data or {}),
                "power": FP10_POWER_ON if on else FP10_POWER_STANDBY,
            }
        )

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
        ok = await self.hass.async_add_executor_job(
            self.api.set_properties, self.device.did, properties, self.device.host
        )
        if not ok:
            raise HomeAssistantError("Dreame FP10 property write failed")
        if optimistic_data:
            self.async_set_updated_data({**(self.data or {}), **optimistic_data})
            return
        await self.async_request_refresh()
