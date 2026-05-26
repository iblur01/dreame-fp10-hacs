"""Switch platform for Dreame FP10 vendor settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity


@dataclass(frozen=True, kw_only=True)
class DreameFP10SwitchDescription(SwitchEntityDescription):
    """Switch description."""


SWITCHES: tuple[DreameFP10SwitchDescription, ...] = (
    DreameFP10SwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        icon="mdi:lock",
    ),
    DreameFP10SwitchDescription(
        key="sound",
        translation_key="sound",
        icon="mdi:volume-high",
    ),
    DreameFP10SwitchDescription(
        key="led_breathe",
        translation_key="led_breathe",
        icon="mdi:led-on",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FP10 switches."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameFP10Switch(coordinator, description) for description in SWITCHES
    )


class DreameFP10Switch(DreameFP10Entity, SwitchEntity):
    """Dreame FP10 switch entity."""

    entity_description: DreameFP10SwitchDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10SwitchDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return switch state."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return value == 1

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the setting on."""
        await self.coordinator.async_set_bool(self.entity_description.key, True)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the setting off."""
        await self.coordinator.async_set_bool(self.entity_description.key, False)
