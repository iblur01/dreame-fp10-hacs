# Diagnostics and troubleshooting

This integration is cloud polling. A failure can come from the Dreame account,
the cloud routing endpoint, the purifier itself, or a property the device does
not actually provide. The diagnostics below separate those cases.

## Quick triage

| Symptom | Likely cause | What to check |
| --- | --- | --- |
| All entities unavailable, `Cloud status = error`, `Last cloud error = connection_error` | Network, Dreame Cloud outage, or wrong regional endpoint | Run `dreame_fp10.test_connection`; check HA logs and the Dreame app |
| `Cloud status = auth_error` | Password changed, token rejected, account locked | Home Assistant starts a reauthentication flow; run the connection test to confirm |
| `Cloud status = error`, `Last cloud error = empty_response` | Cloud answered but returned no properties; purifier asleep/offline or request lost | Run the connection test and `read_properties`; check power and Wi-Fi |
| `Cloud status = error`, `Last cloud error = property_error` | Cloud rejected every property (device offline or firmware mismatch) | Inspect `property_errors` in diagnostics; check the Dreame app |
| `Cloud status = degraded`, `Missing properties > 0` | Partial cloud response; some properties were dropped | Check which properties are missing and whether the temperature is among them |
| Temperature `unavailable`, `Temperature status = not_reported` | The purifier answered `3.3 = 0`; it has no usable temperature reading | Nothing to fix: the entity is intentionally unavailable; `raw_value` is `0` |
| Temperature `unavailable`, `Temperature status = missing` | `3.3` was absent from the last cloud response | Run `read_properties` for `3.3`; check `last_valid_at` |
| Temperature shows a value but `Temperature status = missing` | The last poll dropped `3.3`; the previous value was carried forward | Check `last_valid_at` and the missing-properties list; the value is stale |
| Temperature `unavailable`, `Temperature status = unknown` | The last poll failed before `3.3` could be evaluated | Check `Cloud status` and `Last cloud error` first; a successful poll restores the temperature state |
| Repairs shows "Dreame FP10 purifier unreachable" | Three consecutive polls failed | Open the diagnostic entities and run the connection test |

## Diagnostic entities

These entities live in the diagnostic category and remain available while the
purifier is unreachable, so they can explain the failure:

- `binary_sensor.<device>_cloud_connection` — on when the last poll succeeded.
- `sensor.<device>_cloud_status` — `ok`, `degraded`, `error` or `auth_error`.
- `sensor.<device>_last_error` — last error category (`connection_error`,
  `empty_response`, `property_error`, `auth_error`, `unexpected_error`,
  `none`) with message and timestamp attributes.
- `sensor.<device>_consecutive_failures` — number of failed polls in a row.
- `sensor.<device>_missing_properties` — count of entity-backed properties
  missing from the last successful response, with the list, optional properties,
  per-property error codes and last-seen times. It is `unknown` after a failed
  poll, because the response never arrived.
- `sensor.<device>_last_successful_update` — timestamp of the last poll that
  returned at least one property.
- `sensor.<device>_response_time` — cloud round-trip time for the last poll.
- `sensor.<device>_temperature_status` — `ok`, `not_reported` (cloud returned
  `0`/`null`), `missing` (`3.3` absent), or `unknown` after a failed poll.

The temperature entity itself also exposes `temperature_status`, `raw_value`,
`last_valid_value` and `last_valid_at` attributes.

## Download diagnostics

Open **Settings → Devices & services → Dreame FP10 → ⋮ → Download diagnostics**.
The JSON file contains:

- the config entry data and options with username, password, device id, MAC and
  host redacted;
- the last poll: duration, attempts, requested/received counts, missing
  properties, per-property error codes and raw values;
- the last 20 failures;
- consecutive failure count and last error details;
- temperature diagnostics;
- coordinator state and property last-seen timestamps.

Never post the raw file without checking it first: non-sensitive values such as
the purifier name or model are kept to make support easier.

## Actions

The diagnostic actions are admin-only and return a response. In **Developer
tools → Actions**, select one, enable **Return response**, call it, and inspect
the YAML result. They also work while the config entry is in `SETUP_RETRY` or
`SETUP_ERROR`, which is when a connection test is most useful. The
`start_auto_clean` control action requests self-cleaning, has no response
payload, and requires a loaded config entry. Its historic service ID is retained.

### `dreame_fp10.start_auto_clean`

Requests U2513 filter self-cleaning (`SIID 7`, `AIID 1`) using the configured
device ID. The call is available only while that config entry is loaded. A
normal cloud/API return does not confirm physical success; inspect the `7.1`
status sensor. No stop or filter-reset action is exposed.

```yaml
action: dreame_fp10.start_auto_clean
data: {}
```

The U2513 self-cleaning page reads property `7.1`. Its UI interprets `1` as
running, `2` as success, and `3` as anomaly; other values remain unknown. The
status sensor exposes those states and retains the raw value in its attributes.
The start action's response is not proof of physical success. AIID 2 is used by
the result flow to reset self-cleaning state and is not exposed.

The simple countdown property `6.8` is a writable integer-hour number from
`0` to `12` (`0` is off). Property `6.2` exposes only fixed-time power on/off
schedules through the action below. The color temperature property `6.13` is
statically present, but absent from the live U2513 screen, so it is not exposed.

### `dreame_fp10.manage_schedule`

Reads property `6.2`, updates one pipeline-format slot and writes the complete
list back. Slots are one-based and limited to five. Create uses the next slot;
delete compacts later slots. Updates preserve condition fields and opaque action
tail values already present in that record. The supported trigger is a fixed
time with an eight-bit repeat mask; supported actions are power on/off. With
`end_time`, only an on schedule is accepted, matching the app's paired
power-on/power-off form. Conditional sensor triggers and other action types are
not exposed. No schedule was created or tested against the device.

```yaml
action: dreame_fp10.manage_schedule
data:
  operation: create
  slot: 1
  name: Evening
  time: "22:30"
  repeat_mask: "01111100"
  action: on
```

### `dreame_fp10.test_connection`

Runs a fresh login, fetches the account device list, and reads all FP10
properties with a dedicated client. It does not touch the coordinator's session
or polling schedule.

```yaml
action: dreame_fp10.test_connection
data: {}
response_variable: report
```

Useful fields in the response:

- `auth_ok`, `login_ms`, `device_list_ms`, `property_read_ms`;
- `device_found_in_account`, `device_online` and `device_status_fields` when the
  cloud exposes an online flag;
- `properties`, `missing_properties`, `property_errors`, `raw_properties`;
- `assessment`: a human-readable conclusion, including whether temperature is
  `0`, missing or valid.

### `dreame_fp10.read_properties`

Live raw MiOT dump. Without `properties`, every FP10 property is read. With a
list, only the requested `siid.piid` values are read.

```yaml
action: dreame_fp10.read_properties
data:
  properties:
    - "3.3"
    - "3.2"
response_variable: report
```

Each entry in `raw_properties` contains `siid`, `piid`, `key`, `value` and
`error_code`.

## Failure categories

- `auth_error` — login or token refresh rejected. Home Assistant starts a
  reauthentication flow; the entry is not usable until the password is updated.
- `connection_error` — DNS, TCP, TLS, HTTP or timeout failure against Dreame
  Cloud. The integration retries the property read once, then marks entities
  unavailable.
- `empty_response` — HTTP 200 but no usable property in the response, after a
  retry. Usually the purifier is offline or the cloud lost the request.
- `property_error` — the cloud returned per-property error codes and no value.
  The codes are kept in diagnostics and in the `property_errors` attributes;
  they are device/cloud errors, not HA parsing errors.
- `unexpected_error` — unexpected exception. The full traceback is in the HA
  log; the sanitized message is in diagnostics.

A partial response (some values returned, some missing) is not an error: the
last known values are kept and missing entity-backed keys are reported as
`degraded` with their last-seen timestamps. The experimental PM10 property can be absent without degrading overall device
status. Other generic properties are omitted from polling; request an explicit
`siid.piid` pair through `read_properties` if needed.

The unreachable repair issue is removed after a successful poll, when the entry
is unloaded or deleted, and when authentication fails (the reauthentication flow
takes over). This prevents a stale repair from surviving a reload or device
removal.

## Temperature semantics

- `3.3` non-zero (positive or negative) → valid temperature.
- `3.3 == 0` or `null` → normalized to `None`, temperature entity
  `unavailable`, `Temperature status = not_reported`, raw value preserved.
- `3.3` absent → previous value kept if available, `Temperature status =
  missing`, `last_valid_at` tells how old the displayed value is.

This distinction matters because a real 0 °C reading and a missing sensor can
look identical in the raw payload. For an indoor purifier, an explicit `0` is
treated as "not reported", which matches the FP10 behavior.
