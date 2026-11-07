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
  - presets for auto, sleep, Custom (existing HA preset key `manual`) and pet
  - explicit `fan.turn_on` and `fan.turn_off` support for current Home
    Assistant Core versions
- Sensors for PM2.5, PM10, air quality level, temperature, humidity and filter
  life.
- Temperature is reported as unavailable when the purifier returns `0`
  (meaning it has no usable temperature reading) instead of polluting history
  with a fake 0 °C value.
- Switches for child lock, key sound and ambient light breathing mode.
- Ambient brightness selector for the supported levels: off, low (30), natural
  (50), and bright (80). A legacy number entity snaps to those levels.
- HEPA and CombBox (hair-trap) filter life and lifespan-value sensors.
- Fast cloud polling, defaulting to 10 seconds and configurable from 5 to 60
  seconds.
- Reliable batched MiOT reads with a retry for empty responses. Transport
  errors now mark entities unavailable instead of silently keeping stale data.
- Diagnostic entities, a downloadable diagnostics file and two diagnostic
  actions to understand disconnections and missing properties. See
  [docs/DIAGNOSTICS.md](docs/DIAGNOSTICS.md).
- Admin action `dreame_fp10.start_auto_clean` requests U2513 self-cleaning;
  its historic service ID is retained.
- Read-only diagnostic entities expose self-cleaning WaterApi properties.
- The simple countdown uses a confirmed 0–12 hour number control. Fixed-time
  power schedules support one-slot create/update/delete/enable. Supported
  brightness and display-unit settings
  use discrete selectors.
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

| Feature | MiOT mapping | Status and Home Assistant behavior |
| --- | --- | --- |
| Power state/control | property `2.1`, action `2.1` | U2513 app action payload uses integer `1=on`, `0=standby`; HA now sends the same numeric type. Static APK mapping; no physical toggle was performed for this change. |
| Mode | `2.3`: `0=Auto`, `1=Power`, `2=Sleep`, `3=Custom`, `4=Pet` | Plugin enum. `Power` is CN-only and is not offered as a HA preset. Existing preset key `manual` is retained for compatibility, but shown as **Custom**. |
| Custom fan speed | `2.4`, range `1-10`, default `5` | HA exposes the percentage only in Auto/Custom; it is unknown in Sleep/Pet because `2.4` can be a stale setting. Entering Custom writes mode and speed together. |
| Humidity, temperature, air-quality key, PM2.5 | `3.2`, `3.3`, `3.4`, `3.5` | U2513 properties. `3.4`: `-1=unknown`, `1=excellent`, `2=good`, `3=average`, `4=poor`; decoded category is additive and raw level remains. |
| PM10 | generic AirQuality property `3.6` | Optional experimental diagnostic entity with the legacy registry ID; U2513 UI/config does not verify this property, and its absence does not degrade cloud status. |
| HEPA filter life / days remaining | `4.1`, `4.2` | App displays `4.2` as days; live screen showed 80% and 577 days. |
| Hair-trap (CombBox) life / days remaining | `4.5`, `4.6` | App displays `4.6` as days; live screen showed 35% and 32 days. |
| Start filter self-cleaning | action `7/1` | Uses configured DID with no inputs. The `7.1` status sensor reports running/success/anomaly; action response alone does not confirm physical success. |
| Filter self-cleaning status | `7.1` | The U2513 page maps `1=running`, `2=success`, `3=anomaly`; other/default values remain unknown. |
| Simple countdown | `6.8`, integer range `0-12`, step `1` | Confirmed integer hours; `0` means off. The advanced scheduler is separately exposed through `manage_schedule`. |
| Fixed-time power schedules | `6.2` | `manage_schedule` supports at most five pipeline-format records, fixed-time power on/off, optional paired on/off times, and repeat masks. Edits preserve opaque fields; delete compacts later slots. No schedule was created or run for validation. |
| Ambient brightness | `6.6` | Discrete levels `0=off`, `30=Faible`, `50=Naturel`, `80=Lumineux`; select entity offers only supported values. Legacy number snaps to the nearest level. |
| Temperature/weight display units | `6.4`, `6.11` | Selectors write Celsius/Fahrenheit and kg/lb. Temperature sensor remains in Celsius. |
| Pet platform and weight | SIID `5`, PIID `2`/`3` | U2513 AirpPet mapping exists, but the app requires a platform and none was detected live. No weighing entities or actions are exposed. |
| Child lock | `6.10` | Confirmed U2513 setting. |
| Ambient light breathing mode | `6.12`, `1=breathing`, `0=fixed brightness` | Confirmed. The existing switch ID is retained; ON means breathing mode, OFF means fixed brightness mode. |
| Key sound | `6.17` | Confirmed U2513 setting. |

Filter reset actions are present in the plugin (`4/1` for HEPA and `4/3` for
CombBox) but are intentionally not exposed: resetting filter life changes
maintenance state. The result page uses AIID 2 to reset state after completion; a separate stop
method has ambiguous DID handling, so AIID 2 is not exposed as a stop action.
Only fixed-time power on/off is supported from the advanced scheduler; sensor
triggers and other actions remain unavailable. Generic properties `3.9`,
`3.12`, and `3.13` are not polled as U2513 sensors; they
remain available for explicit raw reads through the diagnostic action. The `2.3`
mode enum and `2.4` speed range come from the plugin fallback model; not every
mode transition has been replayed against the live unit. `2.1` state semantics also remain to be
rechecked.

When brightness is changed while breathing is active, the app writes `6.12=0`
then the selected `6.6` value. HA mirrors this behavior. The older number entity is retained for
compatibility and snaps to the supported brightness levels.

## Temperature availability

The current temperature handling treats `3.3 = 0` as not reported and marks the
entity unavailable. The U2513 plugin maps humidity, temperature, air-quality key,
and PM2.5. Generic mapping `3.6` to PM10 is not verified for U2513; PM10 is
optional and excluded from degraded-status checks. The last
valid value and reason are kept in entity attributes and in the
`Temperature status` diagnostic sensor. Missing and partial cloud responses
are also tracked in diagnostics.

## Notes

This integration is cloud polling. A 10 second interval is intentionally brisk
for quick sensor feedback, but it still depends on Dreame Cloud latency and rate
limits.
