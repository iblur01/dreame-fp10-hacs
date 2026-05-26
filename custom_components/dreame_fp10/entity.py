"""Shared Dreame FP10 entity helpers."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import DreameFP10Coordinator


class DreameFP10Entity(CoordinatorEntity[DreameFP10Coordinator]):
    """Base class for Dreame FP10 entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DreameFP10Coordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.did}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Return Home Assistant device registry information."""
        identifiers: set[tuple[str, str]] = {(DOMAIN, self.coordinator.device.did)}
        connections: set[tuple[str, str]] = set()
        if self.coordinator.device.mac:
            connections.add((dr.CONNECTION_NETWORK_MAC, self.coordinator.device.mac))

        return DeviceInfo(
            identifiers=identifiers,
            connections=connections,
            manufacturer="Dreame",
            model=self.coordinator.device.model,
            name=self.coordinator.device.name,
        )
