"""Config flow for the Dreame FP10 integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME

from .api import DreameCloudAPI, DreameFP10AuthError, DreameFP10Error
from .const import (
    CONF_COUNTRY,
    CONF_DEVICE_NAME,
    CONF_DID,
    CONF_HOST,
    CONF_MAC,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    COUNTRY_OPTIONS,
    DEFAULT_COUNTRY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    MODEL_FP10,
    SUPPORTED_MODELS,
)

_LOGGER = logging.getLogger(__name__)


def _device_name(device: dict[str, Any]) -> str:
    """Return the best available device name."""
    device_info = device.get("deviceInfo") or {}
    return (
        device.get("customName")
        or device.get("displayName")
        or device_info.get("displayName")
        or device.get("name")
        or "Dreame FP10"
    )


def _device_model(device: dict[str, Any]) -> str:
    """Return the Dreame model identifier."""
    return str(device.get("model") or device.get("subModel") or "")


def _device_did(device: dict[str, Any]) -> str:
    """Return the device id."""
    return str(device.get("did") or "")


def _is_supported_device(device: dict[str, Any]) -> bool:
    """Return true if the discovered device looks like a supported purifier."""
    model = _device_model(device)
    category = str(device.get("categoryPath") or "")
    return model in SUPPORTED_MODELS or category.endswith("/airp")


def _entry_data(login_data: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    """Build persisted config entry data."""
    return {
        CONF_USERNAME: login_data[CONF_USERNAME],
        CONF_PASSWORD: login_data[CONF_PASSWORD],
        CONF_COUNTRY: login_data[CONF_COUNTRY],
        CONF_DID: _device_did(device),
        CONF_HOST: device.get("bindDomain"),
        CONF_DEVICE_NAME: _device_name(device),
        CONF_MODEL: _device_model(device) or MODEL_FP10,
        CONF_MAC: device.get("mac"),
    }


class DreameFP10ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Dreame FP10 setup through the UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._login_data: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Return the options flow handler."""
        return DreameFP10OptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle account credentials and cloud discovery."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api = DreameCloudAPI(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                user_input[CONF_COUNTRY],
            )
            try:
                await self.hass.async_add_executor_job(api.login)
                devices = await self.hass.async_add_executor_job(api.get_devices)
            except DreameFP10AuthError:
                errors["base"] = "invalid_auth"
            except DreameFP10Error as ex:
                _LOGGER.debug("Dreame FP10 discovery failed: %s", ex)
                errors["base"] = "cannot_connect"
            else:
                supported_devices = [
                    device
                    for device in devices
                    if _device_did(device) and _is_supported_device(device)
                ]
                if not supported_devices:
                    errors["base"] = "no_supported_devices"
                else:
                    self._login_data = user_input
                    self._devices = supported_devices
                    return await self.async_step_device()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_COUNTRY, default=DEFAULT_COUNTRY): vol.In(
                        COUNTRY_OPTIONS
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Let the user pick a discovered purifier and test it."""
        if not self._login_data or not self._devices:
            return await self.async_step_user()

        errors: dict[str, str] = {}
        device_options = {
            _device_did(device): f"{_device_name(device)} ({_device_model(device)})"
            for device in self._devices
        }

        if user_input is not None:
            selected_did = str(user_input[CONF_DID])
            device = next(
                item for item in self._devices if _device_did(item) == selected_did
            )
            api = DreameCloudAPI(
                self._login_data[CONF_USERNAME],
                self._login_data[CONF_PASSWORD],
                self._login_data[CONF_COUNTRY],
            )
            try:
                await self.hass.async_add_executor_job(api.login)
                values = await self.hass.async_add_executor_job(
                    api.get_properties,
                    selected_did,
                    [
                        {"siid": 2, "piid": 1},
                        {"siid": 2, "piid": 3},
                        {"siid": 3, "piid": 5},
                    ],
                    device.get("bindDomain"),
                )
            except DreameFP10Error as ex:
                _LOGGER.debug("Dreame FP10 device test failed: %s", ex)
                errors["base"] = "cannot_connect"
            else:
                if not values:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(f"{DOMAIN}_{selected_did}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_device_name(device),
                        data=_entry_data(self._login_data, device),
                        options={CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL.seconds},
                    )

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {vol.Required(CONF_DID): vol.In(device_options)}
            ),
            errors=errors,
        )


class DreameFP10OptionsFlow(config_entries.OptionsFlow):
    """Handle Dreame FP10 options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Configure polling options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self._config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.seconds
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL),
                    )
                }
            ),
        )
