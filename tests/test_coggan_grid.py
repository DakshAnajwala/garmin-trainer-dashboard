"""Power-profile grid.

The design rests on one property: a category band must sit at the SAME height
in every duration column, even though the W/kg numbers differ wildly (Cat 3 is
~12.5 W/kg at 5s but ~3.9 W/kg at 20min). If that breaks, the chart silently
lies — the lines would still draw, just against meaningless bands. So it's
pinned first and hardest.
"""
from __future__ import annotations

import pytest

from config.coggan_profile import CATEGORIES, COGGAN_WKG_BY_DURATION
from services import coggan

WEIGHT = 60.0
GRID_DURATIONS = [5, 60, 300, 1200]


def a_curve(**by_duration) -> dict[int, float]:
    """Keys are the athlete's own curve durations — note d15, not d5: the 5s
    column deliberately reads the 15s best (see _GRID_COLUMNS)."""
    return {int(k.lstrip("d")): v for k, v in by_duration.items()}


class TestBandAlignment:
    def test_a_category_lands_at_the_same_height_in_every_column(self):
        for cat in CATEGORIES:
            ys = []
            for d in GRID_DURATIONS:
                edges = coggan._band_edges(COGGAN_WKG_BY_DURATION[d])
                ys.append(coggan._wkg_to_y(COGGAN_WKG_BY_DURATION[d][cat], edges))
            assert len(set(round(y, 6) for y in ys)) == 1, f"{cat} misaligned: {ys}"

    def test_bands_are_contiguous_and_ordered(self):
        edges = coggan._band_edges(COGGAN_WKG_BY_DURATION[300])
        for lower, upper in zip(edges, edges[1:]):
            assert lower["high"] == upper["low"]
            assert lower["low"] < lower["high"]

    def test_y_increases_with_watts(self):
        edges = coggan._band_edges(COGGAN_WKG_BY_DURATION[1200])
        ys = [coggan._wkg_to_y(w, edges) for w in (2.5, 3.0, 4.0, 5.0, 6.5)]
        assert ys == sorted(ys)

    def test_out_of_range_clamps_into_the_drawable_area(self):
        """A rider off the top (or an absurd value) must still draw, at the
        edge — not fly off the canvas or crash."""
        edges = coggan._band_edges(COGGAN_WKG_BY_DURATION[1200])
        assert coggan._wkg_to_y(0.1, edges) == 0.0
        assert coggan._wkg_to_y(99.0, edges) == len(edges)

    def test_y_to_wkg_inverts_wkg_to_y_inside_the_range(self):
        edges = coggan._band_edges(COGGAN_WKG_BY_DURATION[60])
        for wkg in (5.0, 6.6, 7.6, 9.5):
            assert coggan._y_to_wkg(coggan._wkg_to_y(wkg, edges), edges) == pytest.approx(wkg, abs=0.01)


class TestGridShape:
    def _grid(self, **windows):
        return coggan.build_grid(WEIGHT, 220.0, windows)

    def test_ladder_rows_sit_inside_bands_not_on_their_edges(self):
        """Rows centred in each band; a boundary reads as the line between two
        rows rather than striking through one."""
        g = self._grid(**{"All time": a_curve(d15=700, d60=400, d300=280, d1200=230)})
        assert len(g["rows"]) == len(g["bands"]) * coggan._ROWS_PER_BAND
        for r in g["rows"]:
            assert abs(r["y"] - round(r["y"])) > 1e-6, f"row {r['y']} sits on a band edge"

    def test_rows_run_top_down(self):
        g = self._grid(**{"All time": a_curve(d15=700, d60=400, d300=280, d1200=230)})
        ys = [r["y"] for r in g["rows"]]
        assert ys == sorted(ys, reverse=True)

    def test_pro_uci_is_a_real_category_not_a_synthetic_band(self):
        """Regression: Pro/UCI was flagged synthetic because its *upper edge* is
        extrapolated. The category itself is a published threshold, and shading
        it as invented would tell the athlete something false."""
        g = self._grid(**{"All time": a_curve(d15=700, d60=400, d300=280, d1200=230)})
        by_name = {b["name"]: b for b in g["bands"]}
        assert by_name["Pro/UCI"]["is_category"] is True
        assert by_name["Below Cat 5"]["is_category"] is False
        assert by_name["Pro/UCI"]["extrapolated_edge"] is True  # the edge, not the band

    def test_every_real_category_has_a_band(self):
        g = self._grid(**{"All time": a_curve(d15=700, d60=400, d300=280, d1200=230)})
        names = [b["name"] for b in g["bands"]]
        for cat in CATEGORIES:
            assert cat in names

    def test_no_weight_reports_rather_than_guessing(self):
        g = coggan.build_grid(None, 220.0, {"All time": a_curve(d15=700)})
        assert g["available"] is False
        assert "weight" in g["reason"].lower()


class TestSeries:
    def test_points_carry_watts_wkg_and_category(self):
        g = coggan.build_grid(WEIGHT, 220.0, {"All time": a_curve(d15=700, d60=400, d300=280, d1200=230)})
        pt = next(p for p in g["series"][0]["points"] if p["duration_s"] == 60)
        assert pt["watts"] == 400
        assert pt["wkg"] == pytest.approx(400 / WEIGHT, abs=0.01)
        assert pt["category"] == coggan._category_for(400 / WEIGHT, COGGAN_WKG_BY_DURATION[60])

    def test_windows_stay_separate(self):
        g = coggan.build_grid(WEIGHT, 220.0, {
            "42 days": a_curve(d15=600, d60=350, d300=260, d1200=220),
            "All time": a_curve(d15=700, d60=400, d300=280, d1200=230),
        })
        assert [s["name"] for s in g["series"]] == ["42 days", "All time"]
        recent = next(p for p in g["series"][0]["points"] if p["duration_s"] == 5)
        alltime = next(p for p in g["series"][1]["points"] if p["duration_s"] == 5)
        assert recent["watts"] < alltime["watts"]

    def test_20min_column_is_ftp_anchored(self):
        """Same rule as services/ftp.py: an in-ride 20min is submaximal, so a
        higher tested FTP must win that column rather than be undercut."""
        g = coggan.build_grid(WEIGHT, 250.0, {"All time": a_curve(d15=700, d1200=200)})
        pt = next(p for p in g["series"][0]["points"] if p["duration_s"] == 1200)
        assert pt["watts"] == 250.0

    def test_5s_column_reads_the_15s_best_and_says_so(self):
        """The athlete's curve has 15s, not a true 5s. The substitution is
        deliberate and must stay declared, not silently presented as 5s."""
        g = coggan.build_grid(WEIGHT, 220.0, {"All time": {15: 740, 60: 400}})
        pt = next(p for p in g["series"][0]["points"] if p["duration_s"] == 5)
        assert pt["watts"] == 740
        col = next(c for c in g["columns"] if c["duration_s"] == 5)
        assert col["source_duration_s"] == 15
        assert "15s" in col["note"]

    def test_empty_window_is_dropped_not_drawn_at_zero(self):
        g = coggan.build_grid(WEIGHT, None, {"42 days": {}, "All time": a_curve(d15=700)})
        assert [s["name"] for s in g["series"]] == ["All time"]

    def test_all_points_are_drawable(self):
        g = coggan.build_grid(WEIGHT, 220.0, {"All time": a_curve(d15=9999, d60=1, d300=280, d1200=230)})
        for p in g["series"][0]["points"]:
            assert 0 <= p["y"] <= len(g["bands"])
