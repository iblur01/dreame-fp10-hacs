"""Diagnostics support for the Dreame FP10 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import (
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    DOMAIN,
)
from .coordinator import DreameFP10Coordinator

TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_DID,
    CONF_MAC,
    CONF_HOST,
    "access_token",
    "accessToken",
    "refresh_token",
    "refreshToken",
    "token",
    "authorization",
    "uid",
    "serial_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Dreame FP10 config entry."""
    coordinator: DreameFP10Coordinator | None = hass.data.get(DOMAIN, {}).get(
        entry.entry_id
    )
    integration = await async_get_integration(hass, DOMAIN)

    data = dict(entry.data)
    payload: dict[str, Any] = {
        "integration": {
            "domain": DOMAIN,
            "version": integration.version,
        },
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": data,
            "options": dict(entry.options),
        },
        "device": {
            "name": data.get(CONF_DEVICE_NAME),
            "model": data.get(CONF_MODEL),
            "did": data.get(CONF_DID),
            "host": data.get(CONF_HOST),
            "mac": data.get(CONF_MAC),
        },
        "coordinator": None,
        "api": None,
    }

    if coordinator is not None:
        payload["device"] = {
            "name": coordinator.device.name,
            "model": coordinator.device.model,
            "did": coordinator.device.did,
            "host": coordinator.device.host,
            "mac": coordinator.device.mac,
        }
        payload["coordinator"] = coordinator.diagnostics_summary()
        payload["api"] = {
            "country": coordinator.api.country,
            "authenticated": coordinator.api.authenticated,
            "token_expires_in": coordinator.api.token_expires_in,
        }
    else:
        payload["error"] = "coordinator_not_loaded"

    return async_redact_data(payload, TO_REDACT)
