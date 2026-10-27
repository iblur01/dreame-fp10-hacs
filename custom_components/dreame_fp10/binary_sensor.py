"""Binary sensor platform for Dreame FP10 diagnostics."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FP10 diagnostic binary sensors."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([DreameFP10CloudConnection(coordinator)])


class DreameFP10CloudConnection(DreameFP10Entity, BinarySensorEntity):
    """Report whether the last cloud poll succeeded."""

    _attr_translation_key = "cloud_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DreameFP10Coordinator) -> None:
        super().__init__(coordinator, "cloud_connection")

    @property
    def available(self) -> bool:
        """Keep the connectivity sensor available when disconnected."""
        return True

    @property
    def is_on(self) -> bool:
        """Return true when the last cloud poll succeeded."""
        return self.coordinator.last_update_success

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the current cloud status and failure counters."""
        coordinator = self.coordinator
        return {
            "cloud_status": coordinator.cloud_status,
            "consecutive_failures": coordinator.consecutive_failures,
            "last_error_type": coordinator.last_error_type,
            "last_successful_update": (
                coordinator.last_successful_update.isoformat()
                if coordinator.last_successful_update
                else None
            ),
        }
