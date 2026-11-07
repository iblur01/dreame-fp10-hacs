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
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.const import UnitOfDensity

    PM25_CONCENTRATION_UNIT = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER
except ImportError:  # Home Assistant before 2026.10
    from homeassistant.const import (
        CONCENTRATION_MICROGRAMS_PER_CUBIC_METER as PM25_CONCENTRATION_UNIT,
    )

from .const import (
    DOMAIN,
    MATTER_CLUSTER_AIR_QUALITY,
    MATTER_CLUSTER_HEPA_FILTER_MONITORING,
    MATTER_CLUSTER_RELATIVE_HUMIDITY_MEASUREMENT,
    MATTER_CLUSTER_TEMPERATURE_MEASUREMENT,
)
from .coordinator import DreameFP10Coordinator
from .entity import DreameFP10Entity
from .state import (
    AIR_QUALITY_CATEGORY_OPTIONS,
    CLOUD_STATUS_OPTIONS,
    INTERNAL_PROPERTY_KEYS,
    SELF_CLEANING_STATUS_OPTIONS,
    TEMPERATURE_KEY,
    TEMPERATURE_STATUS_OPTIONS,
    air_quality_category,
    self_cleaning_status,
)


@dataclass(frozen=True, kw_only=True)
class DreameFP10SensorDescription(SensorEntityDescription):
    """Sensor description with Matter mapping metadata."""

    matter_cluster: str | None = None
    registry_key: str | None = None


SENSORS: tuple[DreameFP10SensorDescription, ...] = (
    DreameFP10SensorDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=PM25_CONCENTRATION_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
    ),
    DreameFP10SensorDescription(
        key="pm10",
        translation_key="pm10",
        registry_key="tvoc",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=PM25_CONCENTRATION_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    DreameFP10SensorDescription(
        key="air_quality_level",
        translation_key="air_quality_level",
        icon="mdi:air-filter",
        state_class=SensorStateClass.MEASUREMENT,
        matter_cluster=MATTER_CLUSTER_AIR_QUALITY,
    ),
    DreameFP10SensorDescription(
        key="air_quality_category",
        translation_key="air_quality_category",
        device_class=SensorDeviceClass.ENUM,
        options=AIR_QUALITY_CATEGORY_OPTIONS,
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
    ),
    DreameFP10SensorDescription(
        key="carbon_metric",
        translation_key="carbon_metric",
        native_unit_of_measurement=UnitOfTime.DAYS,
        icon="mdi:filter-clock",
        state_class=SensorStateClass.MEASUREMENT,
    ),
)

DIAGNOSTIC_SENSORS: tuple[DreameFP10SensorDescription, ...] = (
    DreameFP10SensorDescription(
        key="cloud_status",
        translation_key="cloud_status",
        device_class=SensorDeviceClass.ENUM,
        options=CLOUD_STATUS_OPTIONS,
        icon="mdi:cloud-question",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="last_error",
        translation_key="last_error",
        icon="mdi:cloud-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="consecutive_failures",
        translation_key="consecutive_failures",
        icon="mdi:counter",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="missing_properties",
        translation_key="missing_properties",
        icon="mdi:cloud-remove-outline",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="last_successful_update",
        translation_key="last_successful_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="response_time",
        translation_key="response_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="temperature_status",
        translation_key="temperature_status",
        device_class=SensorDeviceClass.ENUM,
        options=TEMPERATURE_STATUS_OPTIONS,
        icon="mdi:thermometer-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    DreameFP10SensorDescription(
        key="self_cleaning_status",
        translation_key="self_cleaning_status",
        device_class=SensorDeviceClass.ENUM,
        options=SELF_CLEANING_STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
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
    async_add_entities(
        DreameFP10DiagnosticSensor(coordinator, description)
        for description in DIAGNOSTIC_SENSORS
    )


class DreameFP10Sensor(DreameFP10Entity, SensorEntity):
    """Dreame FP10 sensor entity."""

    entity_description: DreameFP10SensorDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10SensorDescription,
    ) -> None:
        super().__init__(coordinator, description.registry_key or description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Return false when the purifier does not provide a temperature."""
        if self.entity_description.key == TEMPERATURE_KEY:
            value = (self.coordinator.data or {}).get(TEMPERATURE_KEY)
            if value is None:
                return False
            try:
                if float(value) == 0:
                    return False
            except (TypeError, ValueError):
                pass
        return super().available

    @property
    def native_value(self) -> Any:
        """Return the current sensor value."""
        if self.entity_description.key == "air_quality_category":
            return air_quality_category(
                (self.coordinator.data or {}).get("air_quality_level")
            )

        if self.entity_description.key == "pm10":
            attributes["mapping_status"] = "experimental_generic_miot_mapping"
        return (self.coordinator.data or {}).get(self.entity_description.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose Matter mapping and temperature diagnostics."""
        attributes: dict[str, Any] = {}
        if self.entity_description.matter_cluster is not None:
            attributes["matter_cluster"] = self.entity_description.matter_cluster

        if self.entity_description.key == TEMPERATURE_KEY:
            temperature = self.coordinator.temperature
            attributes.update(
                {
                    "temperature_status": temperature.status,
                    "raw_value": temperature.raw_value,
                    "last_valid_value": temperature.last_valid_value,
                    "last_valid_at": (
                        temperature.last_valid_at.isoformat()
                        if temperature.last_valid_at
                        else None
                    ),
                }
            )

        if self.entity_description.key == "air_quality_category":
            attributes["raw_air_quality_key"] = (self.coordinator.data or {}).get(
                "air_quality_level"
            )

        return attributes or None


class DreameFP10DiagnosticSensor(DreameFP10Entity, SensorEntity):
    """Diagnostic sensor that remains available when the cloud is failing."""

    entity_description: DreameFP10SensorDescription

    def __init__(
        self,
        coordinator: DreameFP10Coordinator,
        description: DreameFP10SensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Keep diagnostics visible even when the purifier is unreachable."""
        return True

    @property
    def native_value(self) -> Any:
        """Return the diagnostic value."""
        key = self.entity_description.key
        coordinator = self.coordinator

        if key == "cloud_status":
            return coordinator.cloud_status
        if key == "last_error":
            return coordinator.last_error_type or "none"
        if key == "consecutive_failures":
            return coordinator.consecutive_failures
        if key == "missing_properties":
            if coordinator.last_poll is None or not coordinator.last_poll.success:
                return None
            return len(coordinator.missing_entity_properties)
        if key == "last_successful_update":
            return coordinator.last_successful_update
        if key == "response_time":
            if coordinator.last_poll is None:
                return None
            return round(coordinator.last_poll.duration * 1000, 1)
        if key == "temperature_status":
            status = coordinator.temperature.status
            if status in TEMPERATURE_STATUS_OPTIONS:
                return status
            return None
        if key == "self_cleaning_status":
            return self_cleaning_status(coordinator.data.get(key))
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the details behind each diagnostic value."""
        key = self.entity_description.key
        coordinator = self.coordinator
        poll = coordinator.last_poll

        if key == "cloud_status":
            return {
                "last_error_type": coordinator.last_error_type,
                "last_error_message": coordinator.last_error_message,
                "last_error_at": (
                    coordinator.last_error_at.isoformat()
                    if coordinator.last_error_at
                    else None
                ),
                "last_successful_update": (
                    coordinator.last_successful_update.isoformat()
                    if coordinator.last_successful_update
                    else None
                ),
                "consecutive_failures": coordinator.consecutive_failures,
            }

        if key == "last_error":
            return {
                "message": coordinator.last_error_message,
                "at": (
                    coordinator.last_error_at.isoformat()
                    if coordinator.last_error_at
                    else None
                ),
                "consecutive_failures": coordinator.consecutive_failures,
            }

        if key == "missing_properties":
            if poll is None:
                return None
            if not poll.success:
                return {
                    "success": False,
                    "error_type": poll.error_type,
                    "error_message": poll.error_message,
                    "requested": poll.requested,
                    "attempts": poll.attempts,
                }
            missing = coordinator.missing_entity_properties
            internal_missing = [
                name for name in poll.missing if name in INTERNAL_PROPERTY_KEYS
            ]
            return {
                "properties": missing,
                "internal_properties": internal_missing,
                "property_errors": dict(poll.property_errors),
                "requested": poll.requested,
                "received": poll.received,
                "last_seen": {
                    name: coordinator.property_last_seen[name].isoformat()
                    for name in missing
                    if name in coordinator.property_last_seen
                },
            }

        if key == "response_time":
            if poll is None:
                return None
            return {
                "success": poll.success,
                "attempts": poll.attempts,
                "received": poll.received,
                "requested": poll.requested,
                "started_at": poll.started_at.isoformat(),
            }

        if key == "temperature_status":
            return coordinator.temperature.as_dict()

        if key == "self_cleaning_status":
            return {"miot_property": "7.1", "raw_value": coordinator.data.get(key)}

        return None
