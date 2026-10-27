# Dreame FP10 Air Purifier for Home Assistant

Custom Home Assistant integration for the Dreame FP10 / Furcatch Air Purifier
FP10. It is structured for HACS and uses the Dreame Cloud MiOT command path
found during reverse engineering.

## Features

- HACS-compatible custom integration.
- UI setup wizard with Dreame Cloud login test.
- Device discovery step that lists compatible purifiers and tests live FP10
  properties before setup finishes.
- Native Home Assistant `fan` entity for the purifier, with:
  - on / standby
  - percentage speed mapped to FP10 manual speed 1-10
  - preset modes: `auto`, `sleep`, `manual`, `pet`
  - explicit `fan.turn_on` and `fan.turn_off` support for current Home
    Assistant Core versions
- Sensors for PM2.5, TVOC, air quality level, temperature, humidity and filter
  life.
- Temperature is reported as unavailable when the purifier returns `0`
  (meaning it has no usable temperature reading) instead of polluting history
  with a fake 0 °C value.
- Switches for child lock, sound and LED breathe mode.
- Number entity for LED brightness.
- Fast cloud polling, defaulting to 10 seconds and configurable from 5 to 60
  seconds.
- Reliable batched MiOT reads with a retry for empty responses. Transport
  errors now mark entities unavailable instead of silently keeping stale data.
- Diagnostic entities, a downloadable diagnostics file and two diagnostic
  actions to understand disconnections and missing properties. See
  [docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md).
- Automatic reauthentication when the Dreame Cloud rejects the account
  password, and a repair issue after three consecutive failed polls once the
  entry has loaded.
- Immediate local feedback when setting manual speed; the next poll still
  reconciles with the purifier's real cloud state.

## Installation with HACS

1. Add this repository as a custom HACS integration repository.
2. Install "Dreame FP10 Air Purifier".
3. Restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration**.
5. Search for **Dreame FP10 Air Purifier**.
6. Enter your Dreame account region and credentials.
7. Select the detected purifier.

## Diagnostics and back-office

The integration exposes enough state to explain *why* the purifier is
disconnected or why a property is missing:

- **Diagnostic entities** (hidden from normal dashboards by their
  `diagnostic` category):
  - `Cloud connection` binary sensor;
  - `Cloud status` (`ok`, `degraded`, `error`, `auth_error`);
  - `Last cloud error`, `Consecutive failures`, `Cloud response time`;
  - `Missing properties` with the list and last-seen time of each
    entity-backed property (`unknown` after a failed poll);
  - `Last successful update`;
  - `Temperature status` (`ok`, `not_reported`, `missing`, or `unknown`
    after a failed poll).
- **Download diagnostics** from the integration entry menu (⋮ →
  *Download diagnostics*). The file contains the last poll, failure history,
  per-property errors, temperature diagnostics and coordinator state, with
  credentials and identifiers redacted.
- **Actions** available in *Developer tools → Actions*:
  - `dreame_fp10.test_connection` runs a fresh login, device-list lookup and
    live property read, then returns an assessment (including the cloud online
    flag when the API exposes it);
  - `dreame_fp10.read_properties` dumps raw MiOT properties, optionally for a
    list of `siid.piid` values.

Example in Developer tools → Actions (enable *Return response*):

```yaml
action: dreame_fp10.test_connection
data: {}
response_variable: report
```

The report is written to `report` and shows whether the failure is
authentication, the cloud device being offline, an empty response, or a
specific rejected/missing property. Full troubleshooting guidance lives in
[docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md).

## Matter-oriented model

Home Assistant currently models purifiers as `fan` entities, so the FP10 is
exposed as a native fan plus sensors and settings. The entity model is aligned
with Matter's Air Purifier, Fan Control, Air Quality and filter-monitoring
clusters. See [docs/MATTER_MAPPING.md](docs/MATTER_MAPPING.md).

## Known protocol mapping

| Feature | MiOT mapping |
| --- | --- |
| Power state | `2.1`, where `1=on`, `2=standby` |
| Power control | action `2.1` with input `{"piid": 1, "value": true/false}` |
| Mode | `2.3`, where `0=auto`, `2=sleep`, `3=manual`, `4=pet` |
| Manual speed | `2.4`, range `1-10`; manual mode must be active |
| Humidity | `3.2` |
| Temperature | `3.3` |
| Air quality level | `3.4` |
| PM2.5 | `3.5` |
| TVOC | `3.6` |
| HEPA filter | `4.1`, `4.2` |
| Carbon filter | `4.5`, `4.6` |
| LED brightness | `6.6` |
| Child lock | `6.10` |
| LED breathe | `6.12` |
| Sound | `6.17` |

## Temperature availability

Some FP10 units do not expose a temperature sensor even though property `3.3`
exists in the MiOT model. In that case the cloud returns `0`. The integration
normalizes that value to *unavailable* so the temperature entity does not show
a false 0 °C. The last valid value and the reason are kept in the entity
attributes and in the `Temperature status` diagnostic sensor. Missing and
partial cloud responses are also tracked in diagnostics instead of being
silently hidden.

## Notes

This integration is cloud polling. A 10 second interval is intentionally brisk
for quick sensor feedback, but it still depends on Dreame Cloud latency and rate
limits.
