"""Diagnostic actions for the Dreame FP10 integration."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_CONFIG_ENTRY_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import service

from .api import (
    DreameCloudAPI,
    DreameFP10AuthError,
    DreameFP10ConnectionError,
    DreameFP10EmptyResponseError,
    DreameFP10Error,
    DreameFP10PropertyError,
)
from .const import CONF_COUNTRY, CONF_DID, CONF_HOST, DOMAIN
from .coordinator import FP10_PROPERTIES
from .state import (
    assess_probe,
    device_online_hint,
    device_status_fields,
    sanitize_error_message,
)

SERVICE_TEST_CONNECTION = "test_connection"
SERVICE_READ_PROPERTIES = "read_properties"

ENTRY_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

READ_PROPERTIES_SCHEMA = ENTRY_SCHEMA.extend(
    {
        vol.Optional("properties"): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _resolve_entry(hass: HomeAssistant, config_entry_id: str | None) -> ConfigEntry:
    """Return a Dreame FP10 config entry, even while it is not loaded.

    The diagnostic actions only need the persisted credentials and device
    metadata. They must keep working while the entry is in SETUP_RETRY or
    SETUP_ERROR, because that is exactly when they are most useful.
    """
    if config_entry_id:
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise ServiceValidationError(
                f"Config entry {config_entry_id} is not a Dreame FP10 entry"
            )
        return entry

    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise ServiceValidationError("No Dreame FP10 config entry is configured")
    if len(entries) > 1:
        raise ServiceValidationError(
            "Several Dreame FP10 entries are configured; pass config_entry_id"
        )
    return entries[0]


def _parse_property_specs(
    requested: list[str] | None,
) -> list[tuple[str, int, int]]:
    """Parse optional ``siid.piid`` strings into property tuples."""
    if not requested:
        return [(key, siid, piid) for key, (siid, piid) in FP10_PROPERTIES.items()]

    specs: list[tuple[str, int, int]] = []
    for raw in requested:
        try:
            siid_text, piid_text = raw.split(".", 1)
            siid = int(siid_text)
            piid = int(piid_text)
        except (TypeError, ValueError) as ex:
            raise ServiceValidationError(
                f"Invalid property '{raw}'; expected a siid.piid string such as '3.3'"
            ) from ex
        key = next(
            (name for name, prop in FP10_PROPERTIES.items() if prop == (siid, piid)),
            f"raw_{siid}_{piid}",
        )
        specs.append((key, siid, piid))
    return specs


def _probe(
    username: str,
    password: str,
    country: str,
    did: str,
    host: str | None,
    specs: list[tuple[str, int, int]],
) -> dict[str, Any]:
    """Run a live, read-only diagnostic probe against Dreame Cloud.

    This uses a dedicated API client so it cannot disturb the coordinator's
    token or in-flight requests.
    """
    report: dict[str, Any] = {
        "checked_at": datetime.now(UTC).isoformat(),
        "auth_ok": False,
        "device_found_in_account": None,
        "device_online": None,
        "configured_host": host,
        "properties_requested": len(specs),
        "properties_received": 0,
        "properties": {},
        "raw_properties": [],
        "missing_properties": [],
        "property_errors": {},
        "assessment": [],
    }
    api = DreameCloudAPI(username, password, country)

    try:
        started = time.monotonic()
        api.login()
        report["auth_ok"] = True
        report["login_ms"] = round((time.monotonic() - started) * 1000, 1)

        try:
            started = time.monotonic()
            devices = api.get_devices()
            report["device_list_ms"] = round((time.monotonic() - started) * 1000, 1)
            report["account_device_count"] = len(devices)
            record = next(
                (device for device in devices if str(device.get("did")) == str(did)),
                None,
            )
            report["device_found_in_account"] = record is not None
            if record is not None:
                report["device_online"] = device_online_hint(record)
                report["device_status_fields"] = device_status_fields(record)
                report["device_model"] = record.get("model") or record.get("subModel")
                report["cloud_bind_domain"] = record.get("bindDomain")
        except DreameFP10Error as ex:
            report["device_list_error"] = sanitize_error_message(ex)

        properties = [{"siid": siid, "piid": piid} for _, siid, piid in specs]
        started = time.monotonic()
        result = api.get_properties_detailed(did, properties, host)
        report["property_read_ms"] = round((time.monotonic() - started) * 1000, 1)
        report["properties_received"] = len(result.values)
        report["property_read_attempts"] = result.attempts
        report["properties"] = {
            key: result.values[(siid, piid)]
            for key, siid, piid in specs
            if (siid, piid) in result.values
        }
        report["missing_properties"] = [
            key for key, siid, piid in specs if (siid, piid) not in result.values
        ]
        report["property_errors"] = {
            key: result.errors[(siid, piid)]
            for key, siid, piid in specs
            if (siid, piid) in result.errors
        }
        report["raw_properties"] = [
            {
                "siid": siid,
                "piid": piid,
                "key": key,
                "value": result.values.get((siid, piid)),
                "error_code": result.errors.get((siid, piid)),
            }
            for key, siid, piid in specs
        ]
        report["success"] = True
    except DreameFP10AuthError as ex:
        report["error_type"] = "auth_error"
        report["error"] = sanitize_error_message(ex)
    except DreameFP10EmptyResponseError as ex:
        report["error_type"] = "empty_response"
        report["error"] = sanitize_error_message(ex)
        report["property_read_attempts"] = getattr(ex, "attempts", 0)
    except DreameFP10PropertyError as ex:
        report["error_type"] = "property_error"
        report["error"] = sanitize_error_message(ex)
        report["property_read_attempts"] = getattr(ex, "attempts", 0)
        rejected = getattr(ex, "errors", {})
        report["property_errors"] = {
            key: rejected[(siid, piid)]
            for key, siid, piid in specs
            if (siid, piid) in rejected
        }
    except DreameFP10ConnectionError as ex:
        report["error_type"] = "connection_error"
        report["error"] = sanitize_error_message(ex)
        report["property_read_attempts"] = getattr(ex, "attempts", 0)
    except Exception as ex:  # noqa: BLE001 - diagnostics must never crash
        report["error_type"] = "unexpected_error"
        report["error"] = sanitize_error_message(ex)
    finally:
        api.close()

    report["assessment"] = assess_probe(report)
    return report


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the diagnostic actions once per Home Assistant instance."""
    if hass.services.has_service(
        DOMAIN, SERVICE_TEST_CONNECTION
    ) and hass.services.has_service(DOMAIN, SERVICE_READ_PROPERTIES):
        return

    async def async_test_connection(call: ServiceCall) -> ServiceResponse:
        """Run a live connectivity and property probe."""
        entry = _resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        data = dict(entry.data)
        specs = _parse_property_specs(None)
        return await hass.async_add_executor_job(
            _probe,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_COUNTRY],
            str(data[CONF_DID]),
            data.get(CONF_HOST),
            specs,
        )

    async def async_read_properties(call: ServiceCall) -> ServiceResponse:
        """Read selected raw MiOT properties from the purifier."""
        entry = _resolve_entry(hass, call.data.get(ATTR_CONFIG_ENTRY_ID))
        data = dict(entry.data)
        specs = _parse_property_specs(call.data.get("properties"))
        return await hass.async_add_executor_job(
            _probe,
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
            data[CONF_COUNTRY],
            str(data[CONF_DID]),
            data.get(CONF_HOST),
            specs,
        )

    service.async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_TEST_CONNECTION,
        async_test_connection,
        schema=ENTRY_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_admin_service(
        hass,
        DOMAIN,
        SERVICE_READ_PROPERTIES,
        async_read_properties,
        schema=READ_PROPERTIES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
