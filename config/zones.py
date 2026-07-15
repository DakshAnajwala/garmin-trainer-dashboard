"""Training zone boundaries.

ASSUMPTION: these are the standard Coggan zone schemes — power as % of FTP,
heart rate as % of lactate threshold HR. Widely reproduced across coaching
literature, not independently derived here. Zone *names* and rough intent are
uncontroversial; the exact cut points vary a little between sources.

HR zones matter more than power zones for this athlete right now: outdoor
rides have no power meter until ~Aug 2026, so HR is the only zone signal
available for the majority of riding, including the Saturday team ride.
"""
from __future__ import annotations

# (name, lower bound as fraction of FTP, upper bound). Upper bound of the top
# zone is open-ended — a sprint can be several times FTP.
POWER_ZONES = [
    ("Z1 Recovery", 0.00, 0.55),
    ("Z2 Endurance", 0.55, 0.75),
    ("Z3 Tempo", 0.75, 0.90),
    ("Z4 Threshold", 0.90, 1.05),
    ("Z5 VO2max", 1.05, 1.20),
    ("Z6 Anaerobic", 1.20, 1.50),
    ("Z7 Neuromuscular", 1.50, float("inf")),
]

# As a fraction of lactate threshold HR (config.athlete_profile.LTHR_BPM).
HR_ZONES = [
    ("Z1 Recovery", 0.00, 0.68),
    ("Z2 Endurance", 0.68, 0.83),
    ("Z3 Tempo", 0.83, 0.94),
    ("Z4 Threshold", 0.94, 1.05),
    ("Z5 VO2max", 1.05, float("inf")),
]
