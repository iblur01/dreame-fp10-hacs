"""Pure state helpers for the Dreame FP10 integration.

This module deliberately has no Home Assistant imports so the normalization
rules can be unit-tested without a running Home Assistant instance.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

TEMPERATURE_KEY = "temperature"

# Generic properties that are not part of the U2513 page. PM10 is retained as
# an optional experimental entity, but its absence must not degrade the device.
INTERNAL_PROPERTY_KEYS = frozenset({"pm10"})

TEMPERATURE_STATUS_UNKNOWN = "unknown"
TEMPERATURE_STATUS_OK = "ok"
TEMPERATURE_STATUS_NOT_REPORTED = "not_reported"
TEMPERATURE_STATUS_MISSING = "missing"
TEMPERATURE_STATUS_OPTIONS = [
    TEMPERATURE_STATUS_OK,
    TEMPERATURE_STATUS_NOT_REPORTED,
    TEMPERATURE_STATUS_MISSING,
]

CLOUD_STATUS_OK = "ok"
CLOUD_STATUS_DEGRADED = "degraded"
CLOUD_STATUS_ERROR = "error"
CLOUD_STATUS_AUTH_ERROR = "auth_error"
CLOUD_STATUS_OPTIONS = [
    CLOUD_STATUS_OK,
    CLOUD_STATUS_DEGRADED,
    CLOUD_STATUS_ERROR,
    CLOUD_STATUS_AUTH_ERROR,
]

SELF_CLEANING_STATUS_OPTIONS = ["running", "complete", "error"]
AIR_QUALITY_CATEGORY_OPTIONS = ["unknown", "excellent", "good", "moderate", "poor"]
AMBIENT_BRIGHTNESS_LEVELS = (0, 30, 50, 80)


def self_cleaning_status(value: Any) -> str | None:
    """Map the U2513 SelfCleaningPage status values without guessing defaults."""
    try:
        state = int(value)
    except (TypeError, ValueError):
        return None
    return {1: "running", 2: "complete", 3: "error"}.get(state)


def air_quality_category(value: Any) -> str:
    """Decode the U2513 AirQualityKey used by the app's quality display."""
    try:
        state = int(value)
    except (TypeError, ValueError):
        return "unknown"
    return {-1: "unknown", 1: "excellent", 2: "good", 3: "moderate", 4: "poor"}.get(
        state, "unknown"
    )


def normalize_led_brightness(value: Any) -> int:
    """Snap legacy numeric brightness requests to U2513's supported levels."""
    try:
        requested = float(value)
    except (TypeError, ValueError):
        requested = 30
    return min(AMBIENT_BRIGHTNESS_LEVELS, key=lambda level: abs(level - requested))


def fan_percentage_for_mode(mode: Any, speed: Any) -> int | None:
    """Expose the stored speed only in U2513 modes that display it as current."""
    try:
        mode_value = int(mode)
        speed_value = int(speed)
    except (TypeError, ValueError):
        return None
    if mode_value not in (0, 3) or not 1 <= speed_value <= 10:
        return None
    return speed_value * 10


def manual_speed_properties(mode: Any, speed: Any) -> list[dict[str, int]]:
    """Build the U2513 custom-mode write used by its slider."""
    try:
        current_mode = int(mode)
    except (TypeError, ValueError):
        current_mode = -1
    try:
        speed_value = max(1, min(10, int(speed)))
    except (TypeError, ValueError):
        speed_value = 5
    props = []
    if current_mode != 3:
        props.append({"siid": 2, "piid": 3, "value": 3})
    props.append({"siid": 2, "piid": 4, "value": speed_value})
    return props

_SENSITIVE_PATTERN = re.compile(
    r"(?i)([\"']?\b(?:access_token|accessToken|refresh_token|refreshToken|token|"
    r"password|authorization|dreame-auth|uid)\b[\"']?\s*[:=]\s*)"
    r"(?:(?:bearer|basic)\s+)?(?:\"[^\"]*\"|'[^']*'|[^\s,;\"'}&)]+)"
)
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]+")
_LONG_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_\-+/=.]{40,}")


@dataclass(slots=True)
class MergedState:
    """Result of merging one cloud property snapshot with the previous state."""

    data: dict[str, Any]
    received: tuple[str, ...]
    missing: tuple[str, ...]
    raw_temperature: Any
    temperature_status: str

    @property
    def missing_exposed(self) -> tuple[str, ...]:
        """Return missing keys that are exposed as entities."""
        return tuple(key for key in self.missing if key not in INTERNAL_PROPERTY_KEYS)


def _is_zero(value: Any) -> bool:
    """Return true when a cloud value represents a numeric zero."""
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


def merge_state(
    property_map: Mapping[str, tuple[int, int]],
    raw_values: Mapping[tuple[int, int], Any],
    previous: Mapping[str, Any] | None = None,
) -> MergedState:
    """Merge a raw MiOT snapshot with the previous coordinator state.

    The FP10 cloud sometimes omits a property while returning the rest of the
    snapshot. Missing properties keep their previous value to avoid needless
    flapping. An explicit zero temperature is different: it means the purifier
    does not provide a usable temperature, so it is normalized to ``None`` and
    the temperature entity becomes unavailable.
    """
    previous = previous or {}
    data: dict[str, Any] = {}
    received: list[str] = []
    missing: list[str] = []

    for key, prop in property_map.items():
        if prop in raw_values:
            data[key] = raw_values[prop]
            received.append(key)
        else:
            data[key] = previous.get(key)
            missing.append(key)

    raw_temperature: Any = None
    if TEMPERATURE_KEY in received:
        raw_temperature = data.get(TEMPERATURE_KEY)
        if raw_temperature is None or _is_zero(raw_temperature):
            data[TEMPERATURE_KEY] = None
            temperature_status = TEMPERATURE_STATUS_NOT_REPORTED
        else:
            temperature_status = TEMPERATURE_STATUS_OK
    else:
        temperature_status = TEMPERATURE_STATUS_MISSING

    return MergedState(
        data=data,
        received=tuple(received),
        missing=tuple(missing),
        raw_temperature=raw_temperature,
        temperature_status=temperature_status,
    )


def sanitize_error_message(error: BaseException | str, limit: int = 400) -> str:
    """Return a short, credential-free error message for logs and diagnostics."""
    message = str(error).replace("\n", " ").strip()
    message = _SENSITIVE_PATTERN.sub(r"\1<redacted>", message)
    message = _AUTH_SCHEME_PATTERN.sub(r"\1 <redacted>", message)
    message = _LONG_TOKEN_PATTERN.sub("<redacted>", message)
    if len(message) > limit:
        message = f"{message[:limit]}..."
    return message


def _coerce_online(value: Any) -> bool | None:
    """Interpret the various online flags used by Dreame cloud payloads."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "online", "on", "connected", "active"}:
            return True
        if normalized in {"0", "false", "offline", "off", "disconnected", "inactive"}:
            return False
    return None


def device_online_hint(device: Mapping[str, Any]) -> bool | None:
    """Return the online state advertised by a Dreame device record, if any."""
    for key in (
        "online",
        "isOnline",
        "is_online",
        "deviceOnline",
        "device_online",
        "onlineStatus",
        "online_state",
        "status",
    ):
        if key in device:
            online = _coerce_online(device[key])
            if online is not None:
                return online
    return None


_MISSING = object()


def assess_probe(report: Mapping[str, Any]) -> list[str]:
    """Build a short human-readable assessment of a live probe report."""
    findings: list[str] = []

    if not report.get("auth_ok"):
        findings.append("Dreame Cloud authentication failed.")
        if report.get("error"):
            findings.append(f"Error: {report['error']}")
        return findings

    findings.append("Dreame Cloud authentication succeeded.")

    found = report.get("device_found_in_account")
    if found is True:
        findings.append("The purifier is present in the Dreame account.")
    elif found is False:
        findings.append(
            "The purifier is not present in the Dreame account device list; "
            "it may have been removed or rebound."
        )

    online = report.get("device_online")
    if online is True:
        findings.append("Dreame Cloud reports the purifier as online.")
    elif online is False:
        findings.append(
            "Dreame Cloud reports the purifier as offline. Check power, Wi-Fi "
            "and the Dreame app."
        )
    elif found is True:
        findings.append(
            "The cloud device record does not expose an online flag; rely on "
            "the property read result."
        )

    if report.get("device_list_error"):
        findings.append(
            f"Could not refresh the device list: {report['device_list_error']}"
        )

    received = report.get("properties_received")
    requested = report.get("properties_requested")
    if received is not None and requested:
        if received == 0:
            findings.append("No properties were returned by the cloud.")
        elif received < requested:
            missing = ", ".join(report.get("missing_properties") or [])
            findings.append(
                f"Only {received}/{requested} properties were returned."
                + (f" Missing: {missing}." if missing else "")
            )
        else:
            findings.append(f"All {requested} requested properties were returned.")

    missing_properties = report.get("missing_properties") or []
    properties = report.get("properties") or {}
    temperature = properties.get("temperature", _MISSING)

    if "temperature" in missing_properties:
        findings.append("Temperature (3.3) is missing from the cloud response.")
    elif temperature is not _MISSING:
        try:
            is_zero = float(temperature) == 0
        except (TypeError, ValueError):
            is_zero = temperature is None
        if is_zero:
            findings.append(
                "Temperature (3.3) is 0; the purifier does not provide a "
                "usable temperature in this reading."
            )
        else:
            findings.append(f"Temperature (3.3) is {temperature}.")

    errors = report.get("property_errors") or {}
    if errors:
        formatted = ", ".join(f"{key}={code}" for key, code in sorted(errors.items()))
        findings.append(f"Properties rejected by the cloud: {formatted}.")

    if report.get("error") and report.get("success") is not True:
        findings.append(f"Probe error: {report['error']}")

    if len(findings) == 1:
        findings.append("No problem was detected by this probe.")

    return findings


def device_status_fields(device: Mapping[str, Any]) -> dict[str, Any]:
    """Extract status-related scalar fields from a raw device record.

    This is used by the connection test action to show whether the Dreame
    cloud itself reports the purifier offline. Unknown scalar fields are kept
    so a firmware update that introduces a new status key is visible.
    """
    status: dict[str, Any] = {}
    for key, value in device.items():
        normalized = key.lower()
        if not any(
            marker in normalized
            for marker in ("online", "offline", "status", "active", "last")
        ):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            status[key] = value
    return status
