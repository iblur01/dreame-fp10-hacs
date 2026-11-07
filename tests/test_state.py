"""Unit tests for the pure FP10 state helpers."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

STATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "dreame_fp10"
    / "state.py"
)
spec = importlib.util.spec_from_file_location("dreame_fp10_state", STATE_PATH)
state = importlib.util.module_from_spec(spec)
assert spec is not None and spec.loader is not None
sys.modules[spec.name] = state
spec.loader.exec_module(state)

PROPERTIES = {
    "power": (2, 1),
    "temperature": (3, 3),
    "pm25": (3, 5),
}


class MergeStateTest(unittest.TestCase):
    """Test temperature normalization and carry-forward behavior."""

    def test_zero_temperature_becomes_none(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 3): 0})
        self.assertIsNone(merged.data["temperature"])
        self.assertEqual(merged.raw_temperature, 0)
        self.assertEqual(
            merged.temperature_status, state.TEMPERATURE_STATUS_NOT_REPORTED
        )

    def test_string_zero_temperature_becomes_none(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 3): "0"})
        self.assertIsNone(merged.data["temperature"])
        self.assertEqual(
            merged.temperature_status, state.TEMPERATURE_STATUS_NOT_REPORTED
        )

    def test_zero_temperature_does_not_keep_previous_value(self) -> None:
        merged = state.merge_state(
            PROPERTIES,
            {(3, 3): 0},
            {"temperature": 21.5},
        )
        self.assertIsNone(merged.data["temperature"])
        self.assertEqual(merged.raw_temperature, 0)

    def test_valid_temperature_is_preserved(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 3): 21.5})
        self.assertEqual(merged.data["temperature"], 21.5)
        self.assertEqual(merged.temperature_status, state.TEMPERATURE_STATUS_OK)

    def test_negative_temperature_is_valid(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 3): -3})
        self.assertEqual(merged.data["temperature"], -3)
        self.assertEqual(merged.temperature_status, state.TEMPERATURE_STATUS_OK)

    def test_missing_temperature_keeps_previous_value(self) -> None:
        merged = state.merge_state(
            PROPERTIES,
            {(2, 1): 1},
            {"temperature": 21.5, "power": 2},
        )
        self.assertEqual(merged.data["temperature"], 21.5)
        self.assertEqual(merged.data["power"], 1)
        self.assertEqual(merged.temperature_status, state.TEMPERATURE_STATUS_MISSING)
        self.assertIn("temperature", merged.missing)

    def test_missing_temperature_without_previous_is_none(self) -> None:
        merged = state.merge_state(PROPERTIES, {})
        self.assertIsNone(merged.data["temperature"])
        self.assertEqual(merged.temperature_status, state.TEMPERATURE_STATUS_MISSING)

    def test_zero_pm25_is_a_valid_measurement(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 5): 0})
        self.assertEqual(merged.data["pm25"], 0)

    def test_missing_exposed_ignores_internal_properties(self) -> None:
        merged = state.merge_state(PROPERTIES, {(3, 3): 21})
        self.assertEqual(merged.missing_exposed, ("power", "pm25"))


class SelfCleaningStatusTest(unittest.TestCase):
    """Test only the status values explicitly rendered by the U2513 page."""

    def test_known_status_values(self) -> None:
        self.assertEqual(state.self_cleaning_status(1), "running")
        self.assertEqual(state.self_cleaning_status("2"), "complete")
        self.assertEqual(state.self_cleaning_status(3), "error")

    def test_default_and_unknown_values_remain_unknown(self) -> None:
        self.assertIsNone(state.self_cleaning_status(0))
        self.assertIsNone(state.self_cleaning_status("invalid"))

    def test_air_quality_key_decoding(self) -> None:
        self.assertEqual(state.air_quality_category(-1), "unknown")
        self.assertEqual(state.air_quality_category(1), "excellent")
        self.assertEqual(state.air_quality_category(2), "good")
        self.assertEqual(state.air_quality_category(3), "moderate")
        self.assertEqual(state.air_quality_category(4), "poor")
        self.assertEqual(state.air_quality_category(99), "unknown")

    def test_brightness_snaps_to_supported_levels(self) -> None:
        self.assertEqual(state.normalize_led_brightness(0), 0)
        self.assertEqual(state.normalize_led_brightness(30), 30)
        self.assertEqual(state.normalize_led_brightness(40), 30)
        self.assertEqual(state.normalize_led_brightness(45), 50)
        self.assertEqual(state.normalize_led_brightness(60), 50)
        self.assertEqual(state.normalize_led_brightness(100), 80)

    def test_fan_percentage_only_in_auto_or_custom(self) -> None:
        self.assertEqual(state.fan_percentage_for_mode(0, 5), 50)
        self.assertEqual(state.fan_percentage_for_mode(3, 5), 50)
        self.assertIsNone(state.fan_percentage_for_mode(2, 5))
        self.assertIsNone(state.fan_percentage_for_mode(4, 5))
        self.assertIsNone(state.fan_percentage_for_mode(3, None))

    def test_fan_speed_write_enters_custom_only_when_needed(self) -> None:
        self.assertEqual(
            state.manual_speed_properties(0, 6),
            [
                {"siid": 2, "piid": 3, "value": 3},
                {"siid": 2, "piid": 4, "value": 6},
            ],
        )
        self.assertEqual(
            state.manual_speed_properties(3, 6),
            [{"siid": 2, "piid": 4, "value": 6}],
        )

    def test_air_quality_categories_keep_unknown_values_unknown(self) -> None:
        self.assertEqual(state.air_quality_category(-1), "unknown")
        self.assertEqual(state.air_quality_category(1), "excellent")
        self.assertEqual(state.air_quality_category(2), "good")
        self.assertEqual(state.air_quality_category(3), "moderate")
        self.assertEqual(state.air_quality_category(4), "poor")
        self.assertEqual(state.air_quality_category(99), "unknown")


class ProbeHelpersTest(unittest.TestCase):
    """Test the helpers used by diagnostics and the connection action."""

    def test_online_hint_variants(self) -> None:
        self.assertTrue(state.device_online_hint({"online": True}))
        self.assertFalse(state.device_online_hint({"isOnline": 0}))
        self.assertTrue(state.device_online_hint({"status": "online"}))
        self.assertFalse(state.device_online_hint({"status": "offline"}))
        self.assertIsNone(state.device_online_hint({"name": "FP10"}))

    def test_status_fields_only_keeps_status_scalars(self) -> None:
        fields = state.device_status_fields(
            {
                "online": True,
                "status": "ok",
                "name": "FP10",
                "lastSeen": 123,
                "nested": {"online": False},
            }
        )
        self.assertEqual(fields, {"online": True, "status": "ok", "lastSeen": 123})

    def test_sanitize_error_message_redacts_tokens(self) -> None:
        message = state.sanitize_error_message(
            "access_token=abcdef1234567890 password: hunter2"
        )
        self.assertNotIn("abcdef1234567890", message)
        self.assertNotIn("hunter2", message)

    def test_sanitize_error_message_redacts_json_and_bearer_tokens(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature"
        message = state.sanitize_error_message(
            '{"access_token": "abc123", "refresh_token": "xyz789"} '
            f"Authorization: Bearer {token} Basic YWJjOmRlZg=="
        )
        self.assertNotIn("abc123", message)
        self.assertNotIn("xyz789", message)
        self.assertNotIn(token, message)
        self.assertNotIn("YWJjOmRlZg==", message)
        self.assertIn("<redacted>", message)

        camel = state.sanitize_error_message(
            "accessToken=abc123 refreshToken: xyz789 uid=42"
        )
        self.assertNotIn("abc123", camel)
        self.assertNotIn("xyz789", camel)
        self.assertNotIn("uid=42", camel)

    def test_assessment_flags_zero_temperature(self) -> None:
        findings = state.assess_probe(
            {
                "auth_ok": True,
                "device_found_in_account": True,
                "device_online": True,
                "properties_received": 2,
                "properties_requested": 2,
                "properties": {"temperature": 0, "humidity": 40},
                "missing_properties": [],
                "property_errors": {},
            }
        )
        self.assertTrue(
            any("Temperature (3.3) is 0" in finding for finding in findings)
        )

    def test_assessment_flags_missing_temperature(self) -> None:
        findings = state.assess_probe(
            {
                "auth_ok": True,
                "device_found_in_account": True,
                "device_online": None,
                "properties_received": 1,
                "properties_requested": 2,
                "properties": {"humidity": 40},
                "missing_properties": ["temperature"],
                "property_errors": {},
            }
        )
        self.assertTrue(
            any("missing from the cloud response" in finding for finding in findings)
        )

    def test_assessment_lists_property_errors(self) -> None:
        findings = state.assess_probe(
            {
                "auth_ok": True,
                "device_found_in_account": True,
                "device_online": False,
                "properties_received": 0,
                "properties_requested": 2,
                "properties": {},
                "missing_properties": [],
                "property_errors": {"temperature": -1, "pm25": 7},
                "success": False,
            }
        )
        self.assertTrue(
            any(
                "temperature=-1" in finding and "pm25=7" in finding
                for finding in findings
            )
        )

    def test_assessment_reports_auth_failure(self) -> None:
        findings = state.assess_probe(
            {"auth_ok": False, "error": "invalid credentials"}
        )
        self.assertEqual(findings[0], "Dreame Cloud authentication failed.")


if __name__ == "__main__":
    unittest.main()
