"""Number platform for Dreame FP10 settings."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity


@dataclass(frozen=True, kw_only=True)
class DreameFP10NumberDescription(NumberEntityDescription):
    """Number description."""


NUMBERS: tuple[DreameFP10NumberDescription, ...] = (
    DreameFP10NumberDescription(
        key="led_brightness",
        translation_key="led_brightness",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:brightness-6",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FP10 number entities."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameFP10Number(coordinator, description) for description in NUMBERS
    )


class DreameFP10Number(DreameFP10Entity, NumberEntity):
    """Dreame FP10 number entity."""

    entity_description: DreameFP10NumberDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10NumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        """Return number value."""
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return float(value)

    async def async_set_native_value(self, value: float) -> None:
        """Set number value."""
        if self.entity_description.key == "led_brightness":
            await self.coordinator.async_set_led_brightness(round(value))
