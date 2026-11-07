"""Unit tests for FP10 API error metadata."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

API_PATH = (
    Path(__file__).resolve().parents[1] / "custom_components" / "dreame_fp10" / "api.py"
)
spec = importlib.util.spec_from_file_location("dreame_fp10_api", API_PATH)
api = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = api
spec.loader.exec_module(api)


class FakeResponse:
    """Minimal requests.Response stand-in."""

    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Minimal requests.Session stand-in."""

    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.last_url: str | None = None
        self.last_kwargs: dict[str, object] | None = None

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.last_url = str(args[0]) if args else None
        self.last_kwargs = kwargs
        return self.response

    def close(self) -> None:
        return None


class ErrorMetadataTest(unittest.TestCase):
    """Test that failures retain the details shown in diagnostics."""

    def test_empty_response_keeps_attempts(self) -> None:
        error = api.DreameFP10EmptyResponseError("empty", attempts=2)
        self.assertEqual(error.attempts, 2)

    def test_property_error_keeps_codes(self) -> None:
        error = api.DreameFP10PropertyError(
            "rejected",
            errors={(3, 3): -1, (3, 5): 7},
            requested=2,
            attempts=1,
        )
        self.assertEqual(error.errors, {(3, 3): -1, (3, 5): 7})
        self.assertEqual(error.requested, 2)
        self.assertEqual(error.attempts, 1)


class CloudResponseTest(unittest.TestCase):
    """Test that raw cloud payloads do not leak into error messages."""

    def _api(self, status_code: int, payload: object) -> api.DreameCloudAPI:
        client = api.DreameCloudAPI("user", "password", "eu")
        client._access_token = "access-token"
        client._session = FakeSession(FakeResponse(status_code, payload))
        return client

    def test_command_error_keeps_code_and_message_only(self) -> None:
        client = self._api(
            200,
            {
                "code": 80001,
                "msg": "device offline",
                "access_token": "must-not-leak",
                "data": {"refresh_token": "must-not-leak"},
            },
        )
        with self.assertRaises(api.DreameFP10ConnectionError) as ctx:
            client.send_command("did", "get_properties", [])
        message = str(ctx.exception)
        self.assertIn("code=80001", message)
        self.assertIn("device offline", message)
        self.assertNotIn("must-not-leak", message)

    def test_http_error_does_not_echo_body(self) -> None:
        client = self._api(
            500,
            {"code": 500, "msg": "upstream failed", "password": "must-not-leak"},
        )
        with self.assertRaises(api.DreameFP10ConnectionError) as ctx:
            client.send_command("did", "get_properties", [])
        message = str(ctx.exception)
        self.assertIn("HTTP 500", message)
        self.assertNotIn("must-not-leak", message)

    def test_invalid_json_is_normalized(self) -> None:
        client = self._api(200, ValueError("not json"))
        with self.assertRaises(api.DreameFP10ConnectionError) as ctx:
            client.send_command("did", "get_properties", [])
        self.assertIn("invalid JSON", str(ctx.exception))

    def test_device_discovery_returns_records(self) -> None:
        client = self._api(
            200,
            {
                "code": 0,
                "data": {"page": {"records": [{"did": "did-1", "model": "u2513"}]}},
            },
        )
        self.assertEqual(client.get_devices(), [{"did": "did-1", "model": "u2513"}])

    def test_device_discovery_invalid_shape_is_reported(self) -> None:
        client = self._api(200, {"code": 0, "data": {}})
        with self.assertRaises(api.DreameFP10ConnectionError) as ctx:
            client.get_devices()
        self.assertIn("device list", str(ctx.exception))

    def test_start_auto_clean_uses_the_configured_did_and_exact_action(self) -> None:
        client = self._api(200, {"code": 0, "data": {"result": {"code": 0}}})

        client.start_auto_clean("did-1", "u2513.local")

        session = client._session
        self.assertIsInstance(session, FakeSession)
        assert isinstance(session, FakeSession)
        payload = session.last_kwargs["json"]
        self.assertEqual(
            payload["data"]["params"],
            {"did": "did-1", "siid": 7, "aiid": 1},
        )
        self.assertNotIn("in", payload["data"]["params"])
        self.assertEqual(payload["data"]["method"], "action")
        self.assertIn("-u2513", session.last_url)

    def test_power_action_uses_u2513_integer_input(self) -> None:
        for on, expected in ((True, 1), (False, 0)):
            client = self._api(200, {"code": 0, "data": {"result": {"code": 0}}})
            self.assertTrue(client.set_power("did-1", on, "u2513.local"))
            session = client._session
            self.assertIsInstance(session, FakeSession)
            assert isinstance(session, FakeSession)
            params = session.last_kwargs["json"]["data"]["params"]
            self.assertEqual(params["in"], [{"piid": 1, "value": expected}])
            self.assertIs(type(params["in"][0]["value"]), int)

    def test_simple_countdown_writes_integer_hours_to_6_8(self) -> None:
        client = self._api(
            200,
            {"code": 0, "data": {"result": [{"code": 0}]}},
        )

        self.assertTrue(
            client.set_properties(
                "did-1",
                [{"siid": 6, "piid": 8, "value": 12}],
                "u2513.local",
            )
        )
        session = client._session
        self.assertIsInstance(session, FakeSession)
        assert isinstance(session, FakeSession)
        payload = session.last_kwargs["json"]
        self.assertEqual(payload["data"]["method"], "set_properties")
        self.assertEqual(
            payload["data"]["params"],
            [{"did": "did-1", "siid": 6, "piid": 8, "value": 12}],
        )

    def test_u2513_display_unit_selects_write_exact_properties(self) -> None:
        client = self._api(
            200,
            {"code": 0, "data": {"result": [{"code": 0}, {"code": 0}]}},
        )

        self.assertTrue(
            client.set_properties(
                "did-1",
                [
                    {"siid": 6, "piid": 4, "value": 1},
                    {"siid": 6, "piid": 11, "value": 1},
                ],
            )
        )
        session = client._session
        assert isinstance(session, FakeSession)
        self.assertEqual(
            session.last_kwargs["json"]["data"]["params"],
            [
                {"did": "did-1", "siid": 6, "piid": 4, "value": 1},
                {"did": "did-1", "siid": 6, "piid": 11, "value": 1},
            ],
        )

    def test_brightness_change_leaves_breathing_and_writes_supported_level(self) -> None:
        client = self._api(
            200,
            {"code": 0, "data": {"result": [{"code": 0}, {"code": 0}]}},
        )
        self.assertTrue(
            client.set_properties(
                "did-1",
                [
                    {"siid": 6, "piid": 12, "value": 0},
                    {"siid": 6, "piid": 6, "value": 50},
                ],
            )
        )
        session = client._session
        assert isinstance(session, FakeSession)
        self.assertEqual(
            session.last_kwargs["json"]["data"]["params"],
            [
                {"did": "did-1", "siid": 6, "piid": 12, "value": 0},
                {"did": "did-1", "siid": 6, "piid": 6, "value": 50},
            ],
        )

    def test_advanced_schedule_read_modify_write_preserves_opaque_fields(self) -> None:
        client = self._api(200, {"code": 0, "data": {"result": []}})
        current = "weekday|0|06:00-01111100|tsensor-x|7|opaque-time|opaque-sensor|2-vendor-tail"
        reads: list[object] = []
        writes: list[object] = []
        client.get_properties = lambda did, props, host=None: (
            reads.append((did, props, host)) or {(6, 2): current}
        )
        client.set_properties = lambda did, props, host=None: (
            writes.append((did, props, host)) or True
        )

        result = client.manage_advanced_schedule(
            "did-1",
            operation="update",
            slot=1,
            name="Evening",
            time="20:30",
            repeat_mask="01111100",
            action="off",
            host="u2513.local",
        )

        expected = "Evening|0|20:30-01111100|tsensor-x|7|opaque-time|opaque-sensor|1-vendor-tail"
        self.assertEqual(result["schedule"], expected)
        self.assertTrue(result["changed"])
        self.assertEqual(reads, [("did-1", [{"siid": 6, "piid": 2}], "u2513.local")])
        self.assertEqual(
            writes,
            [
                (
                    "did-1",
                    [{"siid": 6, "piid": 2, "value": expected}],
                    "u2513.local",
                )
            ],
        )

    def test_create_schedule_encodes_defaults_and_period(self) -> None:
        serialized, count = api.edit_advanced_schedule(
            "",
            operation="create",
            slot=1,
            time="22:15",
            end_time="06:45",
            repeat_mask="01111111",
            action="on",
        )
        self.assertEqual(count, 1)
        self.assertEqual(
            serialized,
            "t1|1|22:15-06:45-01111111|-1|0|-1|-1|2-0-0-0",
        )

    def test_schedule_enable_and_delete_preserve_other_records(self) -> None:
        current = "a|1|08:00-10000000|-1|0|-1|-1|2-0-0||b|1|18:00-10000000|-1|0|-1|-1|1-0-0"
        disabled, count = api.edit_advanced_schedule(
            current, operation="enable", slot=2, enabled=False
        )
        self.assertEqual(count, 2)
        self.assertEqual(disabled.split("||")[1].split("|")[1], "0")
        remaining, count = api.edit_advanced_schedule(
            disabled, operation="delete", slot=1
        )
        self.assertEqual(count, 1)
        self.assertEqual(remaining, disabled.split("||")[1])

    def test_schedule_rejects_invalid_inputs_and_legacy_payloads(self) -> None:
        with self.assertRaises(ValueError):
            api.edit_advanced_schedule(
                "", operation="create", slot=1, time="25:99",
                repeat_mask="10000000", action="on",
            )
        with self.assertRaises(ValueError):
            api.edit_advanced_schedule(
                "legacy-format", operation="create", slot=1, time="22:00",
                repeat_mask="10000000", action="on",
            )

    def test_schedule_read_must_contain_non_null_string_before_write(self) -> None:
        for read_values in ({}, {(6, 2): None}, {(6, 2): 123}):
            client = self._api(200, {"code": 0, "data": {"result": []}})
            writes: list[object] = []
            client.get_properties = lambda did, props, host=None, values=read_values: values
            client.set_properties = lambda *args, **kwargs: writes.append(args) or True
            with self.subTest(read_values=read_values), self.assertRaises(ValueError):
                client.manage_advanced_schedule(
                    "did-1",
                    operation="create",
                    slot=1,
                    time="22:00",
                    repeat_mask="10000000",
                    action="on",
                )
            self.assertEqual(writes, [])

    def test_set_properties_requires_complete_matching_acknowledgements(self) -> None:
        request = [
            {"siid": 6, "piid": 4, "value": 1},
            {"siid": 6, "piid": 11, "value": 0},
        ]
        for response in (
            [{"code": 0}],  # partial acknowledgement
            [{"code": 0}, {"code": 0}, {"code": 0}],  # extra acknowledgement
            [
                {"code": 0, "siid": 6, "piid": 4},
                {"code": 0, "siid": 6, "piid": 4},
            ],  # duplicate instead of acknowledging the second property
            [
                {"code": 0, "siid": 6, "piid": 4},
                {"code": 0, "siid": 6, "piid": 9},
            ],  # out-of-target acknowledgement
        ):
            client = self._api(200, {"code": 0, "data": {"result": response}})
            with self.subTest(response=response):
                self.assertFalse(client.set_properties("did-1", request))

    def test_login_error_does_not_echo_body(self) -> None:
        client = api.DreameCloudAPI("user", "password", "eu")
        client._session = FakeSession(FakeResponse(401, {"error": "must-not-leak"}))
        with self.assertRaises(api.DreameFP10AuthError) as ctx:
            client.login()
        self.assertNotIn("must-not-leak", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
