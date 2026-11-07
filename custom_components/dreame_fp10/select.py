"""Select platform for U2513 discrete settings and display units."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity
from .state import normalize_led_brightness


@dataclass(frozen=True, kw_only=True)
class DreameFP10SelectDescription(SelectEntityDescription):
    """Select description with MiOT mapping and option values."""

    miot_property: tuple[int, int]
    option_values: dict[str, int]


SELECTS: tuple[DreameFP10SelectDescription, ...] = (
    DreameFP10SelectDescription(
        key="ambient_brightness",
        translation_key="ambient_brightness",
        miot_property=(6, 6),
        options=("off", "low", "natural", "bright"),
        option_values={"off": 0, "low": 30, "natural": 50, "bright": 80},
        icon="mdi:brightness-6",
    ),
    DreameFP10SelectDescription(
        key="temperature_unit",
        translation_key="temperature_unit",
        miot_property=(6, 4),
        options=("celsius", "fahrenheit"),
        option_values={"celsius": 0, "fahrenheit": 1},
        icon="mdi:thermometer",
    ),
    DreameFP10SelectDescription(
        key="weight_unit",
        translation_key="weight_unit",
        miot_property=(6, 11),
        options=("kilograms", "pounds"),
        option_values={"kilograms": 0, "pounds": 1},
        icon="mdi:weight-kilogram",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up U2513 select controls."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameFP10Select(coordinator, description) for description in SELECTS
    )


class DreameFP10Select(DreameFP10Entity, SelectEntity):
    """Discrete U2513 control or display-unit selector."""

    entity_description: DreameFP10SelectDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10SelectDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_options = list(description.options or ())

    @property
    def current_option(self) -> str | None:
        """Return the option matching the current MiOT value."""
        # The legacy number entity and coordinator use ``led_brightness``;
        # the select has a user-facing key ``ambient_brightness``.
        data_key = (
            "led_brightness"
            if self.entity_description.key == "ambient_brightness"
            else self.entity_description.key
        )
        value = (self.coordinator.data or {}).get(data_key)
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return next(
            (
                option
                for option, mapped_value in self.entity_description.option_values.items()
                if mapped_value == value
            ),
            None,
        )

    async def async_select_option(self, option: str) -> None:
        """Write one supported option through the standard property endpoint."""
        if option not in self.entity_description.option_values:
            raise HomeAssistantError("Unsupported Dreame FP10 select option")

        if self.entity_description.key == "ambient_brightness":
            value = normalize_led_brightness(
                self.entity_description.option_values[option]
            )
            await self.coordinator.async_set_led_brightness(value)
            return
        else:
            value = self.entity_description.option_values[option]

        siid, piid = self.entity_description.miot_property
        await self.coordinator.async_set_properties(
            [{"siid": siid, "piid": piid, "value": value}],
            optimistic_data={self.entity_description.key: value},
        )
