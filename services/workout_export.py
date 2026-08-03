"""Export a structured workout as a Zwift .ZWO file.

ASSUMPTION: .ZWO (plain XML) was chosen over .fit (binary, needs an SDK)
since the athlete already trains on Zwift with a KICKR Core — ZWO is the
more directly usable format for their actual setup.

ASSUMPTION: ZWO has no native "stay anywhere in this band" primitive for a
"range" step (e.g. "10m Z2 110-150W" meaning free variation within a band,
not a steady increase) — it's represented as a <Ramp> between the same
low/high bounds, the closest honest equivalent the format offers.

Cadence: ZWO's <SteadyState>/<Ramp> both accept an optional Cadence attribute
(a single target, not a range — the format has no low/high cadence band).
Steps with a cadence target use the midpoint of cadence_low/high_rpm; steps
without one omit the attribute entirely rather than writing a fabricated
value, so a normal interval still imports exactly as before this feature.
"""
from __future__ import annotations

from xml.sax.saxutils import escape


def _cadence_attr(step: dict) -> str:
    low, high = step.get("cadence_low_rpm"), step.get("cadence_high_rpm")
    if low is None and high is None:
        return ""
    midpoint = round(((low or high) + (high or low)) / 2)
    return f' Cadence="{midpoint}"'


def to_zwo(workout: dict) -> str:
    steps_xml = []
    for step in workout["steps"]:
        duration = step["duration_sec"]
        low = step["target_low_pct_ftp"]
        high = step.get("target_high_pct_ftp")
        cadence = _cadence_attr(step)
        if step["target_type"] in ("ramp", "range") and high is not None:
            steps_xml.append(f'<Ramp Duration="{duration}" PowerLow="{low}" PowerHigh="{high}"{cadence}/>')
        else:
            steps_xml.append(f'<SteadyState Duration="{duration}" Power="{low}"{cadence}/>')

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<workout_file>
  <author>Garmin Trainer Dashboard</author>
  <name>{escape(workout.get("name", "Custom Workout"))}</name>
  <description>{escape(workout.get("description", ""))}</description>
  <sportType>bike</sportType>
  <workout>
    {"".join(steps_xml)}
  </workout>
</workout_file>
"""
