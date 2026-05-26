# Matter-oriented entity mapping

Home Assistant does not have a dedicated `air_purifier` entity domain. Air
purifiers are represented as `fan` entities with preset modes, fan speed and
supporting sensors. This integration keeps the FP10 model close to the Matter
Air Purifier device type so a later Matter bridge can map entities cleanly.

| FP10 feature | Home Assistant entity | Dreame MiOT | Matter cluster target |
| --- | --- | --- | --- |
| Purifier main control | `fan` | `2.1`, `2.3`, `2.4`, action `2.1` | Air Purifier `0x005D`, Fan Control `0x0202` |
| Auto / Sleep / Manual / Pet modes | `fan.preset_mode` | `2.3` | Fan Control presets / Air Purifier mode |
| Manual speed 1-10 | `fan.percentage` | `2.4` with `2.3=3` | Fan Control `0x0202` |
| PM2.5 | `sensor.pm25` | `3.5` | Air Quality `0x005B` |
| TVOC | `sensor.tvoc` | `3.6` | Air Quality `0x005B` |
| Air quality level | `sensor.air_quality_level` | `3.4` | Air Quality `0x005B` |
| Temperature | `sensor.temperature` | `3.3` | Temperature Measurement `0x0402` |
| Humidity | `sensor.humidity` | `3.2` | Relative Humidity Measurement `0x0405` |
| HEPA filter life | `sensor.hepa_life`, `sensor.hepa_days` | `4.1`, `4.2` | HEPA Filter Monitoring `0x0071` |
| Carbon filter life | `sensor.carbon_life`, `sensor.carbon_metric` | `4.5`, `4.6` | Activated Carbon Filter Monitoring `0x0072` |
| Child lock / sound / LED | `switch` and `number` | service `6` | Vendor-specific endpoint or optional Matter features |

The entities expose Matter cluster hints in attributes for debugging and future
bridge work. They are not Matter entities yet; the mapping is intentionally
documented and stable so the control model will not need to be redesigned later.
