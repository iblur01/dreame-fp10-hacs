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
- Sensors for PM2.5, TVOC, air quality level, temperature, humidity and filter
  life.
- Switches for child lock, sound and LED breathe mode.
- Number entity for LED brightness.
- Fast cloud polling, defaulting to 10 seconds and configurable from 5 to 60
  seconds.
- Reliable single-property MiOT reads for FP10 firmware that returns incomplete
  data on broader batches.

## Installation with HACS

1. Add this repository as a custom HACS integration repository.
2. Install "Dreame FP10 Air Purifier".
3. Restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration**.
5. Search for **Dreame FP10 Air Purifier**.
6. Enter your Dreame account region and credentials.
7. Select the detected purifier.

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

## Notes

This integration is cloud polling. A 10 second interval is intentionally brisk
for quick sensor feedback, but it still depends on Dreame Cloud latency and rate
limits.
