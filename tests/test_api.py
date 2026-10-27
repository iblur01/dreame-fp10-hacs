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

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
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

    def test_login_error_does_not_echo_body(self) -> None:
        client = api.DreameCloudAPI("user", "password", "eu")
        client._session = FakeSession(FakeResponse(401, {"error": "must-not-leak"}))
        with self.assertRaises(api.DreameFP10AuthError) as ctx:
            client.login()
        self.assertNotIn("must-not-leak", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
