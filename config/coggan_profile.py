"""Coggan power profile reference bands (W/kg by duration, by category).

ASSUMPTION: these are the widely-circulated "Coggan chart" numbers (originally
from Andrew Coggan / Hunter Allen's "Training and Racing with a Power Meter"),
commonly reproduced across the cycling coaching community — not independently
re-derived or verified against a primary source in this session. Treat as a
reasonable reference, not gospel. Values are W/kg at each duration for the
*bottom* of each category's band (i.e. the minimum to be considered that
category); "World Class"/Pro sits above Cat 1.
"""
from __future__ import annotations

# Duration (seconds) -> {category: W/kg threshold}
CATEGORIES = ["Cat 5", "Cat 4", "Cat 3", "Cat 2", "Cat 1", "Pro/UCI"]

COGGAN_WKG_BY_DURATION = {
    5: {"Cat 5": 9.5, "Cat 4": 11.0, "Cat 3": 12.5, "Cat 2": 14.0, "Cat 1": 15.5, "Pro/UCI": 17.5},
    60: {"Cat 5": 5.0, "Cat 4": 5.8, "Cat 3": 6.6, "Cat 2": 7.6, "Cat 1": 8.4, "Pro/UCI": 9.5},
    300: {"Cat 5": 3.7, "Cat 4": 4.3, "Cat 3": 4.9, "Cat 2": 5.6, "Cat 1": 6.4, "Pro/UCI": 7.6},
    1200: {"Cat 5": 2.8, "Cat 4": 3.3, "Cat 3": 3.9, "Cat 2": 4.5, "Cat 1": 5.3, "Pro/UCI": 6.4},
}
