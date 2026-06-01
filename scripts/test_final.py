#!/usr/bin/env python3
"""Verify the patched api.get_properties returns full state reliably."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API_PATH = REPO / "custom_components" / "dreame_fp10" / "api.py"
TOKENS = REPO.parent / "dreame-fp10-integration" / ".dreame" / "tokens.json"

spec = importlib.util.spec_from_file_location("dreame_api", API_PATH)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

FP10 = {
    "power": (2, 1), "mode": (2, 3), "fan_speed": (2, 4), "humidity": (3, 2),
    "temperature": (3, 3), "air_quality_level": (3, 4), "pm25": (3, 5),
    "tvoc": (3, 6), "tvoc_mirror": (3, 9), "display_index": (3, 12),
    "display_text": (3, 13), "hepa_life": (4, 1), "hepa_days": (4, 2),
    "carbon_life": (4, 5), "carbon_metric": (4, 6), "led_brightness": (6, 6),
    "child_lock": (6, 10), "led_breathe": (6, 12), "sound": (6, 17),
}

cache = json.loads(TOKENS.read_text())
dev = (cache.get("devices") or [])[0]
api = mod.DreameCloudAPI(os.environ["DREAME_USER"], os.environ["DREAME_PASS"],
                         cache.get("country", "eu"))
api.login()
props = [{"siid": s, "piid": p} for s, p in FP10.values()]
N = len(props)

for run in range(6):
    t = time.time()
    vals = api.get_properties(dev["did"], props, dev.get("bindDomain"))
    dt = time.time() - t
    named = {k: vals.get(v) for k, v in FP10.items() if v in vals}
    miss = [k for k, v in FP10.items() if v not in vals]
    print(f"run {run+1}: {len(vals)}/{N}  {dt:.2f}s  missing={miss}")
    if run == 1:
        print("  sample:", {k: named[k] for k in list(named)[:8]})
