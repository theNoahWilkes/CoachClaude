"""Regression cases for owcoach/moments.py, from labelled matches (docs/ow/labels/focus-tests.md).

Run with `python -m pytest tests` (or `python tests/test_moments.py`). Pure Python: no video,
no cv2.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from owcoach.moments import digest, focus_tests, swings  # noqa: E402

# 2026.10.27 - 22.31.54.02 / m02 Runasapi (Moira), 0:58-2:10 and d01: the alive counter,
# the fights, final blows and deaths as the packet has them.
RUNASAPI = {
    "game": {"map": "Runasapi", "result": "victory", "mode": "push", "duration_s": 632.0},
    "alive_series": [[0.0, 5, 5], [61.0, 4, 5], [64.0, 3, 5], [74.5, 5, 5], [78.5, 4, 5], [92.0, 5, 5],
                     [98.0, 5, 4], [99.5, 5, 3], [110.5, 5, 5], [115.0, 5, 4], [117.0, 5, 3], [128.0, 5, 5],
                     [200.0, 5, 5], [223.5, 3, 5], [225.0, 2, 5], [242.0, 5, 5]],
    "hud_game": {"fights": [{"from": "1:05", "to": "1:24", "from_t": 65.0, "to_t": 84.0},
                            {"from": "1:30", "to": "1:44", "from_t": 90.5, "to_t": 104.5},
                            {"from": "3:32", "to": "3:53", "from_t": 212.5, "to_t": 233.5}]},
    "final_blows": [{"id": "k01", "t": 98.5, "clock": "1:38"}, {"id": "k02", "t": 99.5, "clock": "1:40"}],
    "deaths": [{"id": "d01", "t": 229.5, "clock": "3:49", "respawned": {"t": 241.5}}],
}


def test_down_two_lived_is_held_from_facts():
    # The player Faded out at 1:12, 8 s into the 3v5, and lived. A reader on 5 s cells called
    # it "stayed in the fight"; the player: down two is a diagnosis on a death.
    f01 = next(x for x in focus_tests(RUNASAPI) if x["kind"] == "down_two" and x["clock"] == "1:04")
    assert (f01["grade"], f01["death"]) == ("held", None)


def test_down_two_ending_in_death_is_broken():
    d = next(x for x in focus_tests(RUNASAPI) if x["kind"] == "down_two" and x["death"] == "d01")
    assert d["grade"] == "broke"


def test_only_down_two_is_graded_from_facts():
    assert all(x["grade"] is None for x in focus_tests(RUNASAPI) if x["kind"] != "down_two")


def test_swing_finds_the_1_38_double_kill():
    # 4v5 at the start of the 1:30 fight, 5v3 after the player's k01 and k02, player alive.
    s = swings(RUNASAPI)
    assert [(x["clock"], x["before"], x["best"], x["kills"]) for x in s] == [("1:30", "4v5", "5v3", ["k01", "k02"])]


def test_digest_shows_grade_and_swing():
    text = digest(RUNASAPI, "m02", ["When the counter shows your team down two or more and you're still in "
                                    "the fight, stop healing forward and back off to the last wall toward your spawn."])
    assert "m02 1:30-1:44: 4v5 to 5v3, final blows k01, k02" in text
    assert "graded from the facts: held (lived)" in text
    assert "graded from the facts: broke (ended in d01)" in text


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
