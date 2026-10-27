"""Dreame FP10 air purifier integration."""

from __future__ import annotations

from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .coordinator import DreameFP10Coordinator, device_issue_id
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def _async_close_coordinator(
    hass: HomeAssistant,
    coordinator: DreameFP10Coordinator,
    entry_id: str,
) -> None:
    """Stop polling, close the cloud session and clear the coordinator."""
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or domain_data.get(entry_id) is not coordinator:
        return
    domain_data.pop(entry_id, None)
    await coordinator.async_shutdown()
    await coordinator.async_close()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration-level diagnostic actions."""
    await async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dreame FP10 from a config entry."""
    await async_setup_services(hass)
    coordinator = DreameFP10Coordinator.from_entry_data(
        hass,
        dict(entry.data),
        dict(entry.options),
        entry,
    )
    # Also covers a failed platform setup: Home Assistant processes the
    # entry's unload callbacks when setup does not complete.
    entry.async_on_unload(
        partial(_async_close_coordinator, hass, coordinator, entry.entry_id)
    )
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_shutdown()
        await coordinator.async_close()
        raise

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Dreame FP10 config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: DreameFP10Coordinator | None = hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )
        if coordinator is not None:
            await _async_close_coordinator(hass, coordinator, entry.entry_id)
        ir.async_delete_issue(hass, DOMAIN, device_issue_id(entry.entry_id, ""))
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up repair issues and a stale coordinator after entry removal."""
    coordinator: DreameFP10Coordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    if coordinator is not None:
        await _async_close_coordinator(hass, coordinator, entry.entry_id)
    ir.async_delete_issue(hass, DOMAIN, device_issue_id(entry.entry_id, ""))
