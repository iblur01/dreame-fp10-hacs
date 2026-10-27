"""Dreame Cloud API client for the FP10 air purifier."""

from __future__ import annotations

import hashlib
import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

DREAME_SALT = "RAylYC%fmSKp7%Tq"
DREAME_USER_AGENT = "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)"
DREAME_AUTH_BASIC = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
DREAME_TENANT_ID = "000000"
DREAME_RLC = "1c80b3787b2266776bcdc481f37d8fa42ba10a30af81a6df-1"


def _safe_payload_detail(payload: Any) -> str:
    """Return a short error detail without echoing a full cloud response."""
    if not isinstance(payload, dict):
        return ""
    details: list[str] = []
    if (code := payload.get("code")) is not None:
        details.append(f"code={code}")
    message = payload.get("msg") or payload.get("message")
    if isinstance(message, (str, int, float, bool)):
        details.append(" ".join(str(message).split())[:200])
    return f" ({', '.join(details)})" if details else ""


def _response_detail(response: requests.Response) -> str:
    """Return a safe error detail from an HTTP response."""
    try:
        payload = response.json()
    except ValueError:
        return ""
    return _safe_payload_detail(payload)


def _response_json(response: requests.Response, context: str) -> Any:
    """Decode a cloud response or raise a normalized connection error."""
    try:
        return response.json()
    except ValueError as ex:
        raise DreameFP10ConnectionError(
            f"{context} returned invalid JSON (HTTP {response.status_code})"
        ) from ex


class DreameFP10Error(Exception):
    """Base error for Dreame FP10 API calls."""


class DreameFP10AuthError(DreameFP10Error):
    """Authentication failed."""


class DreameFP10ConnectionError(DreameFP10Error):
    """Cloud connection failed."""


class DreameFP10EmptyResponseError(DreameFP10ConnectionError):
    """Cloud answered successfully but returned no usable properties."""

    def __init__(self, message: str, *, attempts: int = 0) -> None:
        super().__init__(message)
        self.attempts = attempts


class DreameFP10PropertyError(DreameFP10ConnectionError):
    """Cloud rejected every requested property."""

    def __init__(
        self,
        message: str,
        *,
        errors: dict[tuple[int, int], int] | None = None,
        requested: int = 0,
        attempts: int = 0,
    ) -> None:
        super().__init__(message)
        self.errors = errors or {}
        self.requested = requested
        self.attempts = attempts


@dataclass(slots=True)
class PropertyReadResult:
    """Detailed result of one MiOT property snapshot."""

    values: dict[tuple[int, int], Any] = field(default_factory=dict)
    errors: dict[tuple[int, int], int] = field(default_factory=dict)
    requested: int = 0
    attempts: int = 0
    elapsed: float = 0.0


class DreameCloudAPI:
    """Small synchronous Dreame Cloud client.

    Home Assistant calls this through async_add_executor_job.
    """

    def __init__(self, username: str, password: str, country: str = "eu") -> None:
        self._username = username
        self._password = password
        self._country = country
        self._session = requests.Session()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._uid: str | None = None
        self._tenant_id = DREAME_TENANT_ID
        self._token_expire: float | None = None
        self._id_counter = itertools.count(1)
        self._id_lock = threading.Lock()

    def _next_request_id(self) -> int:
        """Return a unique request id.

        The Dreame cloud correlates sendCommand responses by id. Reusing a
        constant id makes it return another request's response, so each call
        must carry a fresh id.
        """
        with self._id_lock:
            return next(self._id_counter)

    @property
    def api_url(self) -> str:
        """Return the regional Dreame Cloud API base URL."""
        return f"https://{self._country}.iot.dreame.tech:13267"

    @property
    def uid(self) -> str | None:
        """Return the logged-in Dreame user id."""
        return self._uid

    @property
    def country(self) -> str:
        """Return the configured cloud region."""
        return self._country

    @property
    def authenticated(self) -> bool:
        """Return true when an access token is available."""
        return bool(self._access_token)

    @property
    def token_expires_in(self) -> int | None:
        """Return the remaining access-token lifetime in seconds."""
        if self._token_expire is None:
            return None
        return max(0, int(self._token_expire - time.time()))

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def login(self) -> None:
        """Authenticate against Dreame Cloud."""
        url = f"{self.api_url}/dreame-auth/oauth/token"
        password_hash = hashlib.md5(
            (self._password + DREAME_SALT).encode("utf-8")
        ).hexdigest()
        data = (
            "platform=IOS&scope=all&grant_type=password"
            f"&username={self._username}&password={password_hash}&type=account"
        )
        headers = {
            "User-Agent": DREAME_USER_AGENT,
            "Authorization": DREAME_AUTH_BASIC,
            "Tenant-Id": DREAME_TENANT_ID,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        }
        if self._country == "cn":
            headers["Dreame-Rlc"] = DREAME_RLC

        try:
            response = self._session.post(url, headers=headers, data=data, timeout=10)
        except requests.RequestException as ex:
            raise DreameFP10ConnectionError(str(ex)) from ex

        if response.status_code in (400, 401, 403):
            raise DreameFP10AuthError(
                f"Dreame Cloud rejected the credentials (HTTP {response.status_code})"
            )
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Login failed with HTTP {response.status_code}"
                f"{_response_detail(response)}"
            )

        result = _response_json(response, "Login")
        if not isinstance(result, dict) or "access_token" not in result:
            raise DreameFP10AuthError(
                "Dreame Cloud login response did not contain an access token"
            )

        self._access_token = result["access_token"]
        self._refresh_token = result.get("refresh_token")
        self._uid = result.get("uid")
        self._tenant_id = result.get("tenant_id", DREAME_TENANT_ID)
        self._token_expire = time.time() + result.get("expires_in", 3600) - 120

    def _refresh_login(self) -> None:
        if not self._refresh_token or not self._token_expire:
            if self._access_token:
                return
            self.login()
            return

        if time.time() <= self._token_expire:
            return

        url = f"{self.api_url}/dreame-auth/oauth/token"
        data = (
            "platform=IOS&scope=all&grant_type=refresh_token"
            f"&refresh_token={self._refresh_token}"
        )
        headers = {
            "User-Agent": DREAME_USER_AGENT,
            "Authorization": DREAME_AUTH_BASIC,
            "Tenant-Id": self._tenant_id,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            response = self._session.post(url, headers=headers, data=data, timeout=10)
        except requests.RequestException as ex:
            _LOGGER.debug(
                "Token refresh failed (%s), retrying full login",
                type(ex).__name__,
            )
            self.login()
            return

        if response.status_code != 200:
            self.login()
            return

        try:
            result = response.json()
        except ValueError:
            self.login()
            return
        if not isinstance(result, dict) or "access_token" not in result:
            self.login()
            return

        self._access_token = result["access_token"]
        self._refresh_token = result.get("refresh_token", self._refresh_token)
        self._token_expire = time.time() + result.get("expires_in", 3600) - 120

    def _auth_headers(self) -> dict[str, str]:
        return {
            "User-Agent": DREAME_USER_AGENT,
            "Authorization": DREAME_AUTH_BASIC,
            "Tenant-Id": self._tenant_id,
            "Dreame-Auth": self._access_token or "",
            "Content-Type": "application/json",
            "Accept": "*/*",
        }

    def get_devices(self, _auth_retry: bool = True) -> list[dict[str, Any]]:
        """Return Dreame devices bound to the account."""
        self._refresh_login()

        url = f"{self.api_url}/dreame-user-iot/iotuserbind/device/listV2"
        try:
            response = self._session.post(
                url, headers=self._auth_headers(), json={}, timeout=10
            )
        except requests.RequestException as ex:
            raise DreameFP10ConnectionError(str(ex)) from ex

        if response.status_code == 401:
            if not _auth_retry:
                raise DreameFP10AuthError("Dreame Cloud rejected the token (HTTP 401)")
            self.login()
            return self.get_devices(_auth_retry=False)
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Device discovery failed with HTTP {response.status_code}"
                f"{_response_detail(response)}"
            )

        result = _response_json(response, "Device discovery")
        if (
            not isinstance(result, dict)
            or result.get("code") != 0
            or "data" not in result
        ):
            raise DreameFP10ConnectionError(
                f"Device discovery failed{_safe_payload_detail(result)}"
            )

        data = result.get("data")
        page = data.get("page") if isinstance(data, dict) else None
        records = page.get("records") if isinstance(page, dict) else None
        if not isinstance(records, list):
            raise DreameFP10ConnectionError(
                "Device discovery response did not contain a device list"
            )
        return records

    def send_command(
        self,
        did: str,
        method: str,
        params: Any,
        host: str | None = None,
        _auth_retry: bool = True,
    ) -> Any:
        """Send a raw MiOT command through Dreame Cloud."""
        self._refresh_login()

        host_prefix = f"-{host.split('.')[0]}" if host else ""
        url = f"{self.api_url}/dreame-iot-com{host_prefix}/device/sendCommand"
        request_id = self._next_request_id()
        payload = {
            "did": str(did),
            "id": request_id,
            "data": {
                "did": str(did),
                "id": request_id,
                "method": method,
                "params": params,
            },
        }

        try:
            response = self._session.post(
                url, headers=self._auth_headers(), json=payload, timeout=10
            )
        except requests.RequestException as ex:
            raise DreameFP10ConnectionError(str(ex)) from ex

        if response.status_code == 401:
            if not _auth_retry:
                raise DreameFP10AuthError("Dreame Cloud rejected the token (HTTP 401)")
            self.login()
            return self.send_command(did, method, params, host, _auth_retry=False)
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Command failed with HTTP {response.status_code}"
                f"{_response_detail(response)}"
            )

        result = _response_json(response, "Command")
        if not isinstance(result, dict):
            raise DreameFP10ConnectionError(
                f"Command failed{_safe_payload_detail(result)}"
            )
        if result.get("code") != 0:
            raise DreameFP10ConnectionError(
                f"Command failed{_safe_payload_detail(result)}"
            )

        data = result.get("data")
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        if result.get("success"):
            return {"code": 0}
        return data

    def get_properties(
        self, did: str, properties: list[dict[str, int]], host: str | None = None
    ) -> dict[tuple[int, int], Any]:
        """Read raw MiOT properties by siid/piid in a single batched call."""
        return self.get_properties_detailed(did, properties, host).values

    def get_properties_detailed(
        self, did: str, properties: list[dict[str, int]], host: str | None = None
    ) -> PropertyReadResult:
        """Read raw MiOT properties and retain per-property diagnostics.

        With a unique request id (see _next_request_id) the cloud reliably
        returns every requested property in one get_properties call, so there
        is no need to query each property separately. Transport and empty
        responses are retried once, then raised so the coordinator can mark
        the entities unavailable instead of silently keeping stale values.
        """
        params = [
            {"did": str(did), "siid": prop["siid"], "piid": prop["piid"]}
            for prop in properties
        ]
        wanted = {(prop["siid"], prop["piid"]) for prop in properties}
        result = PropertyReadResult(requested=len(wanted))
        started = time.monotonic()
        last_error: DreameFP10Error | None = None

        # The first call after a fresh session sometimes returns nothing while
        # the device wakes; one retry reliably gets the full snapshot.
        for attempt in range(2):
            result.attempts = attempt + 1
            try:
                response = self.send_command(did, "get_properties", params, host)
            except DreameFP10AuthError:
                raise
            except DreameFP10ConnectionError as ex:
                last_error = ex
                _LOGGER.debug(
                    "Failed batched FP10 property read (attempt %s): %s",
                    attempt + 1,
                    ex,
                )
                if attempt == 0:
                    time.sleep(0.5)
                    continue
                result.elapsed = time.monotonic() - started
                ex.attempts = result.attempts
                raise

            if isinstance(response, list):
                for item in response:
                    if not isinstance(item, dict):
                        continue
                    key = (item.get("siid"), item.get("piid"))
                    if key not in wanted:
                        continue
                    code = item.get("code", -1)
                    if code == 0:
                        result.values[key] = item.get("value")
                    else:
                        result.errors[key] = code
            else:
                last_error = DreameFP10ConnectionError(
                    f"Unexpected get_properties response: {type(response).__name__}"
                )

            if result.values or result.errors:
                break
            if attempt == 0:
                time.sleep(0.5)

        result.elapsed = time.monotonic() - started

        if not result.values and not result.errors:
            result.elapsed = time.monotonic() - started
            if last_error is not None:
                last_error.attempts = result.attempts
                raise last_error
            raise DreameFP10EmptyResponseError(
                "Cloud returned no usable properties after "
                f"{result.attempts} attempt(s)",
                attempts=result.attempts,
            )

        if not result.values:
            codes = ", ".join(str(code) for code in sorted(set(result.errors.values())))
            raise DreameFP10PropertyError(
                f"Cloud rejected all {result.requested} properties (codes: {codes})",
                errors=dict(result.errors),
                requested=result.requested,
                attempts=result.attempts,
            )

        return result

    def set_properties(
        self, did: str, properties: list[dict[str, Any]], host: str | None = None
    ) -> bool:
        """Write raw MiOT properties."""
        params = [{"did": str(did), **prop} for prop in properties]
        result = self.send_command(did, "set_properties", params, host)
        return bool(
            result
            and isinstance(result, list)
            and all(
                isinstance(item, dict) and item.get("code", -1) == 0 for item in result
            )
        )

    def set_power(self, did: str, on: bool, host: str | None = None) -> bool:
        """Turn the FP10 on or place it in standby."""
        result = self.send_command(
            did,
            "action",
            {
                "did": str(did),
                "siid": 2,
                "aiid": 1,
                "in": [{"piid": 1, "value": bool(on)}],
            },
            host,
        )
        return bool(isinstance(result, dict) and result.get("code", -1) == 0)
