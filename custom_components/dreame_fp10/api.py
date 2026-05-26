"""Dreame Cloud API client for the FP10 air purifier."""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

DREAME_SALT = "RAylYC%fmSKp7%Tq"
DREAME_USER_AGENT = "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)"
DREAME_AUTH_BASIC = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
DREAME_TENANT_ID = "000000"
DREAME_RLC = "1c80b3787b2266776bcdc481f37d8fa42ba10a30af81a6df-1"


class DreameFP10Error(Exception):
    """Base error for Dreame FP10 API calls."""


class DreameFP10AuthError(DreameFP10Error):
    """Authentication failed."""


class DreameFP10ConnectionError(DreameFP10Error):
    """Cloud connection failed."""


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

    @property
    def api_url(self) -> str:
        """Return the regional Dreame Cloud API base URL."""
        return f"https://{self._country}.iot.dreame.tech:13267"

    @property
    def uid(self) -> str | None:
        """Return the logged-in Dreame user id."""
        return self._uid

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
            raise DreameFP10AuthError(response.text)
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Login failed with HTTP {response.status_code}: {response.text}"
            )

        result = response.json()
        if "access_token" not in result:
            raise DreameFP10AuthError(str(result))

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
            _LOGGER.debug("Token refresh failed, retrying full login: %s", ex)
            self.login()
            return

        if response.status_code != 200:
            self.login()
            return

        result = response.json()
        if "access_token" not in result:
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

    def get_devices(self) -> list[dict[str, Any]]:
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
            self.login()
            return self.get_devices()
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Device discovery failed with HTTP {response.status_code}: {response.text}"
            )

        result = response.json()
        if result.get("code") != 0 or "data" not in result:
            raise DreameFP10ConnectionError(f"Device discovery failed: {result}")

        return result["data"]["page"]["records"]

    def send_command(
        self, did: str, method: str, params: Any, host: str | None = None
    ) -> Any:
        """Send a raw MiOT command through Dreame Cloud."""
        self._refresh_login()

        host_prefix = f"-{host.split('.')[0]}" if host else ""
        url = f"{self.api_url}/dreame-iot-com{host_prefix}/device/sendCommand"
        payload = {
            "did": str(did),
            "id": 1,
            "data": {
                "did": str(did),
                "id": 1,
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
            self.login()
            return self.send_command(did, method, params, host)
        if response.status_code != 200:
            raise DreameFP10ConnectionError(
                f"Command failed with HTTP {response.status_code}: {response.text}"
            )

        result = response.json()
        if result.get("code") != 0:
            raise DreameFP10ConnectionError(f"Command failed: {result}")

        if result.get("data") and "result" in result["data"]:
            return result["data"]["result"]
        if result.get("success"):
            return {"code": 0}
        return result.get("data")

    def get_properties(
        self, did: str, properties: list[dict[str, int]], host: str | None = None
    ) -> dict[tuple[int, int], Any]:
        """Read raw MiOT properties by siid/piid."""
        values: dict[tuple[int, int], Any] = {}

        for prop in properties:
            params = [{"did": str(did), "siid": prop["siid"], "piid": prop["piid"]}]
            try:
                result = self.send_command(did, "get_properties", params, host)
            except DreameFP10ConnectionError as ex:
                _LOGGER.debug(
                    "Failed reading FP10 property %s.%s: %s",
                    prop["siid"],
                    prop["piid"],
                    ex,
                )
                continue

            if not isinstance(result, list):
                continue

            for item in result:
                if item.get("code", -1) == 0:
                    values[(item["siid"], item["piid"])] = item.get("value")

        return values

    def set_properties(
        self, did: str, properties: list[dict[str, Any]], host: str | None = None
    ) -> bool:
        """Write raw MiOT properties."""
        params = [{"did": str(did), **prop} for prop in properties]
        result = self.send_command(did, "set_properties", params, host)
        return bool(
            result
            and isinstance(result, list)
            and all(item.get("code", -1) == 0 for item in result)
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
