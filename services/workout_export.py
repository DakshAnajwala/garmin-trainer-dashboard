"""Export a structured workout as a Zwift .ZWO file.

ASSUMPTION: .ZWO (plain XML) was chosen over .fit (binary, needs an SDK)
since the athlete already trains on Zwift with a KICKR Core — ZWO is the
more directly usable format for their actual setup.

ASSUMPTION: ZWO has no native "stay anywhere in this band" primitive for a
"range" step (e.g. "10m Z2 110-150W" meaning free variation within a band,
not a steady increase) — it's represented as a <Ramp> between the same
low/high bounds, the closest honest equivalent the format offers.
"""
from __future__ import annotations

from xml.sax.saxutils import escape


def to_zwo(workout: dict) -> str:
    steps_xml = []
    for step in workout["steps"]:
        duration = step["duration_sec"]
        low = step["target_low_pct_ftp"]
        high = step.get("target_high_pct_ftp")
        if step["target_type"] in ("ramp", "range") and high is not None:
            steps_xml.append(f'<Ramp Duration="{duration}" PowerLow="{low}" PowerHigh="{high}"/>')
        else:
            steps_xml.append(f'<SteadyState Duration="{duration}" Power="{low}"/>')

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
