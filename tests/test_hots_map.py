"""The HotS death map (hotscoach.map_facts, map_svg), on a small made-up map.

Run with `python -m pytest tests` (or `python tests/test_hots_map.py`). Pure Python: no replay,
no heroprotocol.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import hotscoach  # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"
ME, ALLY, ENEMY = (dict(pid=i, name=n, hero=h, team=t) for i, n, h, t in
                   ((1, "me", "Rehgar", 0), (2, "ally", "Johanna", 0), (6, "enemy", "Sonya", 1)))


def game():
    """One lane: our core at x 40, keep 60, fort 90; theirs mirrored around the midline at 120."""
    return SimpleNamespace(
        me=ME, pid={p["pid"]: p for p in (ME, ALLY, ENEMY)}, mid_x=120.0,
        towns=[(0, 1, 90.0, 100.0), (0, 1, 60.0, 100.0), (1, 1, 150.0, 100.0), (1, 1, 180.0, 100.0)],
        buildings=[dict(kind="core", team=0, x=40, y=100, lost=None), dict(kind="core", team=1, x=200, y=100, lost=None),
                   dict(kind="fort", team=1, x=150, y=100, lost=301.0), dict(kind="tower", team=0, x=92, y=104, lost=None)],
        camp_spots=[(120.0, 130.0)],
        deaths=[dict(t=65.0, victim=1, x=130.0, y=101.0), dict(t=66.0, victim=2, x=128.0, y=99.0),
                dict(t=200.0, victim=6, x=95.0, y=100.0), dict(t=400.0, victim=1, x=130.5, y=101.0)],
        label=lambda p: p["hero"])


def test_lane_runs_core_to_core():
    mp = hotscoach.map_facts(game())
    assert mp["lanes"] == [[[40, 100], [60.0, 100.0], [90.0, 100.0], [150.0, 100.0], [180.0, 100.0], [200, 100]]]


def test_deaths_numbered_like_the_moments():
    # the player's deaths get d01, d02 in replay order, as analyze() numbers its death reports
    deaths = hotscoach.map_facts(game())["deaths"]
    assert [(d["who"], d["id"]) for d in deaths] == [("you", "d01"), ("ally", None), ("enemy", None), ("you", "d02")]


def test_buildings_are_ours_or_theirs_and_keep_when_they_fell():
    b = hotscoach.map_facts(game())["buildings"]
    assert [(x["kind"], x["side"], x["lost"]) for x in b] == [("core", "us", None), ("core", "them", None),
                                                              ("fort", "them", "5:01"), ("tower", "us", None)]


def test_svg_flips_y_and_steps_overlapping_numbers_aside():
    root = ET.fromstring(hotscoach.map_svg(hotscoach.map_facts(game())))
    marks = [g for g in root.iter(SVG + "g")]
    assert [g.find(SVG + "text").text for g in marks] == ["1", "2"]
    (x1, y1), (x2, y2) = [(float(g.find(SVG + "circle").get("cx")), float(g.find(SVG + "circle").get("cy"))) for g in marks]
    assert y1 == y2 and x2 - x1 >= 17      # the second death on the same spot is moved, not hidden
    camp = root.find(SVG + "polygon")
    core = root.find(SVG + "rect[@rx]")
    assert float(camp.get("points").split()[0].split(",")[1]) < float(core.get("y"))   # higher y = further up


def test_nothing_to_place_gives_no_map():
    assert hotscoach.map_svg({"lanes": [], "buildings": [], "camps": [], "deaths": []}) is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
