"""Fan platform for the Dreame FP10 air purifier."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    FP10_POWER_ON,
    FP10_SPEED_MAX,
    FP10_SPEED_MIN,
    MATTER_CLUSTER_FAN_CONTROL,
    MATTER_DEVICE_TYPE_AIR_PURIFIER,
    MODE_TO_PRESET,
    PRESET_AUTO,
    PRESET_MANUAL,
    PRESET_PET,
    PRESET_SLEEP,
    PRESET_TO_MODE,
)
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the FP10 fan entity."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameFP10Fan(coordinator)])


class DreameFP10Fan(DreameFP10Entity, FanEntity):
    """Dreame FP10 purifier represented as Home Assistant's native fan entity."""

    _attr_name = None
    _attr_translation_key = "air_purifier"
    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
    )
    _enable_turn_on_off_backwards_compatibility = False
    _attr_preset_modes = [
        PRESET_AUTO,
        PRESET_SLEEP,
        PRESET_MANUAL,
        PRESET_PET,
    ]

    def __init__(self, coordinator: DreameFP10Coordinator) -> None:
        super().__init__(coordinator, "air_purifier")

    @property
    def is_on(self) -> bool:
        """Return true when the purifier is on."""
        return self.coordinator.data.get("power") == FP10_POWER_ON

    @property
    def percentage(self) -> int | None:
        """Return fan speed percentage."""
        if not self.is_on:
            return 0
        speed = self.coordinator.data.get("fan_speed")
        if not isinstance(speed, int):
            return None
        return max(0, min(100, speed * 10))

    @property
    def percentage_step(self) -> int:
        """Return the supported percentage step."""
        return 10

    @property
    def preset_mode(self) -> str | None:
        """Return the active purifier mode."""
        return MODE_TO_PRESET.get(self.coordinator.data.get("mode"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the intended Matter cluster mapping."""
        return {
            "matter_air_purifier_device_type": MATTER_DEVICE_TYPE_AIR_PURIFIER,
            "matter_fan_control_cluster": MATTER_CLUSTER_FAN_CONTROL,
        }

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the purifier on."""
        await self.coordinator.async_set_power(True)
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Put the purifier in standby."""
        await self.coordinator.async_set_power(False)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set manual fan speed from a HA percentage."""
        if percentage <= 0:
            await self.async_turn_off()
            return
        if not self.is_on:
            await self.coordinator.async_set_power(True)
        speed = round(percentage / 10)
        speed = max(FP10_SPEED_MIN, min(FP10_SPEED_MAX, speed))
        await self.coordinator.async_set_fan_speed(speed)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the purifier preset mode."""
        if preset_mode not in PRESET_TO_MODE:
            return
        if not self.is_on:
            await self.coordinator.async_set_power(True)
        await self.coordinator.async_set_mode(PRESET_TO_MODE[preset_mode])
