# Matter-oriented entity mapping

Home Assistant does not have a dedicated `air_purifier` entity domain. Air
purifiers are represented as `fan` entities with preset modes, fan speed and
supporting sensors. This integration keeps the FP10 model close to the Matter
Air Purifier device type so a later Matter bridge can map entities cleanly.

| FP10 feature | Home Assistant entity | Dreame MiOT | Matter cluster target |
| --- | --- | --- | --- |
| Purifier main control | `fan` | `2.1`, `2.3`, `2.4`, action `2.1` | Air Purifier device type `0x002D`, Fan Control `0x0202` |
| Auto / Sleep / Custom / Pet modes | `fan.preset_mode` | `2.3` | Fan Control presets / Air Purifier mode |
| Fan speed | `fan.percentage` | `2.4`, displayed only in Auto/Custom | Fan Control `0x0202` |
| PM2.5 | `sensor.pm25` | `3.5` | Air Quality `0x005B` |
| PM10 (experimental) | optional diagnostic sensor with legacy `_tvoc` ID | generic `3.6` | Air Quality `0x005B`; not verified for U2513 |
| Raw air-quality key / category | `sensor.air_quality_level`, `sensor.air_quality_category` | `3.4` | Air Quality `0x005B` |
| Temperature | `sensor.temperature` | `3.3` | Temperature Measurement `0x0402` |
| Humidity | `sensor.humidity` | `3.2` | Relative Humidity Measurement `0x0405` |
| HEPA filter life | `sensor.hepa_life`, `sensor.hepa_days` | `4.1`, `4.2` | HEPA Filter Monitoring `0x0071` |
| CombBox (hair-trap) filter life | `sensor.carbon_life`, `sensor.carbon_metric` (legacy IDs) | `4.5`, `4.6` | Vendor-specific; not an activated-carbon filter mapping |
| Child lock / key sound / ambient light | `switch`, `number`, `select` | `6.6`, `6.10`, `6.12`, `6.17` | Vendor-specific endpoint or optional Matter features |

The entities expose Matter cluster hints in attributes for debugging and future
bridge work. They are not Matter entities yet; the mapping is intentionally
documented and stable so the control model will not need to be redesigned later.

The old sensor registry IDs are retained when their U2513 meaning is corrected,
so existing entity references continue to resolve. The `2.3` mode enum and
`2.4` speed range come from the plugin fallback model, but not all mode
transitions were replayed on the live unit. The U2513 page/config maps humidity, temperature, air-quality key and PM2.5.
Generic `3.6` to PM10 is not verified for U2513 and remains optional. The U2513 app maps `3.4` values `-1/1/2/3/4` to unknown, excellent,
good, average and poor. The decoded category sensor retains the raw key, while the existing level
sensor stays raw. The U2513 app sends power action `2.1` with numeric input
`1` for on and `0` for standby; HA mirrors that payload type. This mapping comes
from static APK evidence and was not physically toggled during this change.

Although the plugin names properties `4.2` and `4.6` `lifespanHours`, the U2513
app renders their values as remaining days. HA exposes these values in days.
