"""Home Assistant level tests for the FP10 coordinator.

These tests are skipped when Home Assistant is not installed. Run them in one
of the verification virtualenvs with this repository on PYTHONPATH.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from datetime import UTC, datetime, timedelta
from types import MappingProxyType, SimpleNamespace
from typing import ClassVar

try:
    import homeassistant  # noqa: F401
except ImportError:  # pragma: no cover - plain Python test environment
    HA_AVAILABLE = False
else:
    from homeassistant.config_entries import ConfigEntry, ConfigEntryState
    from homeassistant.core import HomeAssistant
    from homeassistant.data_entry_flow import FlowResultType
    from homeassistant.helpers import issue_registry as ir

    from custom_components.dreame_fp10 import (
        _async_close_coordinator,
        async_remove_entry,
        config_flow,
    )
    from custom_components.dreame_fp10.api import (
        DreameFP10AuthError,
        DreameFP10ConnectionError,
        PropertyReadResult,
    )
    from custom_components.dreame_fp10.const import DOMAIN
    from custom_components.dreame_fp10.coordinator import (
        FP10_PROPERTIES,
        DreameFP10Coordinator,
        DreameFP10Device,
    )
    from custom_components.dreame_fp10.sensor import (
        DIAGNOSTIC_SENSORS,
        SENSORS,
        DreameFP10DiagnosticSensor,
        DreameFP10Sensor,
    )

    HA_AVAILABLE = True


def _entry(state: object = None) -> ConfigEntry:
    """Create a real ConfigEntry for the coordinator tests."""
    kwargs = {
        "data": {},
        "discovery_keys": MappingProxyType({}),
        "domain": "dreame_fp10",
        "minor_version": 1,
        "options": {},
        "source": "user",
        "subentries_data": None,
        "title": "Test FP10",
        "unique_id": None,
        "version": 1,
    }
    if state is not None:
        kwargs["state"] = state
    return ConfigEntry(**kwargs)


class FakeAPI:
    """API with a programmable property result."""

    def __init__(self) -> None:
        self.result: object = PropertyReadResult()

    def login(self) -> None:
        """No-op login."""

    def close(self) -> None:
        """No-op close."""

    def get_properties_detailed(
        self, did: str, properties: list[dict[str, int]], host: str | None = None
    ) -> PropertyReadResult:
        """Return or raise the programmed result."""
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@unittest.skipUnless(HA_AVAILABLE, "Home Assistant is not installed")
class CoordinatorHATest(unittest.IsolatedAsyncioTestCase):
    """Test coordinator behavior with real Home Assistant objects."""

    async def asyncSetUp(self) -> None:
        self.config_dir = tempfile.mkdtemp(prefix="dreame-fp10-test-")
        self.hass = HomeAssistant(self.config_dir)
        self.api = FakeAPI()
        self.entry = _entry(ConfigEntryState.LOADED)
        self.coordinator = DreameFP10Coordinator(
            self.hass,
            self.api,
            DreameFP10Device("did-1", None, "Test FP10", "dreame.airp.u2513", None),
            timedelta(seconds=60),
            self.entry,
        )

    async def asyncTearDown(self) -> None:
        await self.coordinator.async_shutdown()
        await self.coordinator.async_close()
        await self.hass.async_stop(force=True)
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def _all_values(self, temperature: object) -> PropertyReadResult:
        values = {prop: 1 for prop in FP10_PROPERTIES.values()}
        values[(3, 3)] = temperature
        return PropertyReadResult(
            values=values,
            requested=len(values),
            attempts=1,
        )

    async def test_zero_temperature_makes_entity_unavailable(self) -> None:
        self.api.result = self._all_values(0)
        await self.coordinator.async_refresh()

        self.assertIsNone(self.coordinator.data["temperature"])
        self.assertEqual(self.coordinator.temperature.status, "not_reported")
        self.assertEqual(self.coordinator.temperature.raw_value, 0)

        description = next(item for item in SENSORS if item.key == "temperature")
        entity = DreameFP10Sensor(self.coordinator, description)
        self.assertFalse(entity.available)
        self.assertIsNone(entity.native_value)

    async def test_missing_temperature_keeps_previous_value(self) -> None:
        self.api.result = self._all_values(21.5)
        await self.coordinator.async_refresh()

        self.api.result = PropertyReadResult(
            values={(2, 1): 1},
            requested=1,
            attempts=1,
        )
        await self.coordinator.async_refresh()

        self.assertEqual(self.coordinator.data["temperature"], 21.5)
        self.assertEqual(self.coordinator.temperature.status, "missing")
        self.assertIn("temperature", self.coordinator.missing_entity_properties)

    async def test_failed_polls_create_and_recover_issue(self) -> None:
        error = DreameFP10ConnectionError("device offline")
        error.attempts = 2
        self.api.result = error

        for _ in range(3):
            await self.coordinator.async_refresh()

        registry = ir.async_get(self.hass)
        issue = registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        self.assertIsNotNone(issue)
        self.assertFalse(self.coordinator.last_update_success)
        self.assertEqual(self.coordinator.last_poll.missing, ())
        self.assertEqual(self.coordinator.missing_entity_properties, [])
        self.assertEqual(self.coordinator.last_poll.attempts, 2)

        description = next(
            item for item in DIAGNOSTIC_SENSORS if item.key == "missing_properties"
        )
        entity = DreameFP10DiagnosticSensor(self.coordinator, description)
        self.assertIsNone(entity.native_value)
        self.assertFalse(entity.extra_state_attributes["success"])

        self.api.result = self._all_values(22)
        await self.coordinator.async_refresh()
        self.assertIsNone(
            registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        )
        self.assertTrue(self.coordinator.last_update_success)

    async def test_remove_entry_clears_issue(self) -> None:
        self.api.result = DreameFP10ConnectionError("device offline")
        for _ in range(3):
            await self.coordinator.async_refresh()

        registry = ir.async_get(self.hass)
        self.assertIsNotNone(
            registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        )
        await async_remove_entry(self.hass, self.entry)
        self.assertIsNone(
            registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        )

    async def test_close_helper_removes_coordinator_once(self) -> None:
        self.hass.data[DOMAIN] = {self.entry.entry_id: self.coordinator}
        await _async_close_coordinator(self.hass, self.coordinator, self.entry.entry_id)
        self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN])
        self.assertTrue(self.coordinator._closing)

        # A late unload callback must not close the same coordinator twice.
        await _async_close_coordinator(self.hass, self.coordinator, self.entry.entry_id)
        self.assertNotIn(self.entry.entry_id, self.hass.data[DOMAIN])

    async def test_auth_error_clears_stale_issue(self) -> None:
        self.api.result = DreameFP10ConnectionError("device offline")
        for _ in range(3):
            await self.coordinator.async_refresh()

        registry = ir.async_get(self.hass)
        self.assertIsNotNone(
            registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        )
        self.coordinator._record_failure(
            datetime.now(UTC),
            time.monotonic(),
            "auth_error",
            DreameFP10AuthError("token rejected"),
        )
        self.assertIsNone(
            registry.async_get_issue("dreame_fp10", self.coordinator.issue_id)
        )


class FakeFlowAPI:
    """Minimal DreameCloudAPI replacement for the reauth flow."""

    instances: ClassVar[list[FakeFlowAPI]] = []
    fail_auth = False

    def __init__(self, username: str, password: str, country: str) -> None:
        self.username = username
        self.password = password
        self.country = country
        self.closed = False
        FakeFlowAPI.instances.append(self)

    def login(self) -> None:
        """Authenticate or reject the test password."""
        if FakeFlowAPI.fail_auth:
            raise DreameFP10AuthError("invalid credentials")

    def get_devices(self) -> list[dict[str, object]]:
        """Return an empty device list; the reauth flow only checks success."""
        return []

    def close(self) -> None:
        """Record session cleanup."""
        self.closed = True


class FakeConfigEntries:
    """Minimal config-entry manager for the reauth flow."""

    def __init__(self, entry: SimpleNamespace) -> None:
        self.entry = entry
        self.reloads: list[str] = []
        self.updates: list[dict[str, object]] = []

    def async_get_entry(self, entry_id: str) -> SimpleNamespace | None:
        """Return the test entry."""
        return self.entry if entry_id == self.entry.entry_id else None

    def async_get_known_entry(self, entry_id: str) -> SimpleNamespace:
        """Return the test entry for form placeholders."""
        return self.entry

    def async_update_entry(
        self,
        entry: SimpleNamespace,
        *,
        data: dict[str, object] | None = None,
        **kwargs: object,
    ) -> bool:
        """Apply the new credentials."""
        if data is not None:
            entry.data = data
            self.updates.append(data)
        return True

    def async_schedule_reload(self, entry_id: str) -> None:
        """Record the requested reload."""
        self.reloads.append(entry_id)


@unittest.skipUnless(HA_AVAILABLE, "Home Assistant is not installed")
class ConfigFlowHATest(unittest.IsolatedAsyncioTestCase):
    """Test reauth scheduling without relying on the full flow manager."""

    async def asyncSetUp(self) -> None:
        self.entry = SimpleNamespace(
            data={
                "username": "user@example.com",
                "password": "old-password",
                "country": "eu",
            },
            entry_id="entry-1",
            title="Test FP10",
            update_listeners=[],
        )
        self.config_entries = FakeConfigEntries(self.entry)

        async def _run_in_executor(func: object, *args: object) -> object:
            return func(*args)  # type: ignore[operator]

        self.hass = SimpleNamespace(
            config_entries=self.config_entries,
            async_add_executor_job=_run_in_executor,
        )
        self.original_api = config_flow.DreameCloudAPI
        config_flow.DreameCloudAPI = FakeFlowAPI
        FakeFlowAPI.fail_auth = False
        FakeFlowAPI.instances = []

    async def asyncTearDown(self) -> None:
        config_flow.DreameCloudAPI = self.original_api

    def _flow(self) -> config_flow.DreameFP10ConfigFlow:
        """Create a flow with the attributes normally set by the manager."""
        flow = config_flow.DreameFP10ConfigFlow()
        flow.hass = self.hass
        flow.context = {"source": "reauth", "entry_id": self.entry.entry_id}
        flow.handler = "dreame_fp10"
        flow.flow_id = "flow-1"
        return flow

    async def test_reauth_success_schedules_exactly_one_reload(self) -> None:
        result = await self._flow().async_step_reauth_confirm(
            {"password": "new-password"}
        )

        self.assertEqual(result["type"], FlowResultType.ABORT)
        self.assertEqual(result["reason"], "reauth_successful")
        self.assertEqual(self.entry.data["password"], "new-password")
        self.assertEqual(self.config_entries.reloads, ["entry-1"])
        self.assertTrue(FakeFlowAPI.instances[-1].closed)

    async def test_reauth_invalid_password_does_not_reload(self) -> None:
        FakeFlowAPI.fail_auth = True
        result = await self._flow().async_step_reauth_confirm(
            {"password": "bad-password"}
        )

        self.assertEqual(result["type"], FlowResultType.FORM)
        self.assertEqual(result["errors"], {"base": "invalid_auth"})
        self.assertEqual(self.entry.data["password"], "old-password")
        self.assertEqual(self.config_entries.reloads, [])
        self.assertTrue(FakeFlowAPI.instances[-1].closed)


if __name__ == "__main__":
    unittest.main()
