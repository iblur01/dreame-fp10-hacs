"""Sensor platform for the Dreame FP10 air purifier."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    PERCENTAGE,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    MATTER_CLUSTER_ACTIVATED_CARBON_FILTER_MONITORING,
    MATTER_CLUSTER_AIR_QUALITY,
    MATTER_CLUSTER_HEPA_FILTER_MONITORING,
    MATTER_CLUSTER_RELATIVE_HUMIDITY_MEASUREMENT,
    MATTER_CLUSTER_TEMPERATURE_MEASUREMENT,
)
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity


@dataclass(frozen=True, kw_only=True)
class DreameFP10SensorDescription(SensorEntityDescription):
    """Sensor description with Matter mapping metadata."""

    matter_cluster: str | None = None


SENSORS: tuple[DreameFP10SensorDescription, ...] = (
    DreameFP10SensorDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
    ),
    DreameFP10SensorDescription(
        key="tvoc",
        translation_key="tvoc",
        icon="mdi:molecule",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
    ),
    DreameFP10SensorDescription(
        key="air_quality_level",
        translation_key="air_quality_level",
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
    ),
    DreameFP10SensorDescription(
        key="temperature",
        translation_key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_TEMPERATURE_MEASUREMENT,
    ),
    DreameFP10SensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_RELATIVE_HUMIDITY_MEASUREMENT,
    ),
    DreameFP10SensorDescription(
        key="hepa_life",
        translation_key="hepa_life",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_HEPA_FILTER_MONITORING,
    ),
    DreameFP10SensorDescription(
        key="hepa_days",
        translation_key="hepa_days",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        icon="mdi:calendar-clock",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_HEPA_FILTER_MONITORING,
    ),
    DreameFP10SensorDescription(
        key="carbon_life",
        translation_key="carbon_life",
        native_unit_of_measurement=PERCENTAGE,
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_ACTIVATED_CARBON_FILTER_MONITORING,
    ),
    DreameFP10SensorDescription(
        key="carbon_metric",
        translation_key="carbon_metric",
        icon="mdi:filter-clock",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_ACTIVATED_CARBON_FILTER_MONITORING,
    ),
    DreameFP10SensorDescription(
        key="display_text",
        translation_key="display_text",
        icon="mdi:information-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up FP10 sensors."""
    coordinator: DreameFP10Coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        DreameFP10Sensor(coordinator, description) for description in SENSORS
    )


class DreameFP10Sensor(DreameFP10Entity, SensorEntity):
    """Dreame FP10 sensor entity."""

    entity_description: DreameFP10SensorDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10SensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        return self.coordinator.data.get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose Matter cluster mapping for future bridge work."""
        if self.entity_description.matter_cluster is None:
            return None
        return {"matter_cluster": self.entity_description.matter_cluster}
