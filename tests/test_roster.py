"""Tests for the persistent roster data layer.

IMPORTANT: these must never touch the user's real local_config/roster.json — a
test in this project once clobbered the real calibration. Every test points
roster.ROSTER_PATH at a throwaway temp dir.

Run with: python tests/test_roster.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbcompanion import roster

_REAL_ROSTER_PATH = roster.ROSTER_PATH
_TMP = Path(tempfile.mkdtemp(prefix="bbc_roster_test_"))
roster.ROSTER_PATH = _TMP / "roster.json"

SAMPLE = {
    "name": "Atiq Orcbane",
    "background": "Sellsword",
    "archetype": "Polearm Backline (Battle Forged)",
    "verdict": "good",
    "rating": 9.9,
    "current_stats": {"hp": 60, "melee_skill": 67},
    "stars": {"melee_skill": 2},
    "projected": {"hp": 95, "melee_skill": 97},
}


def _reset():
    if roster.ROSTER_PATH.exists():
        roster.ROSTER_PATH.unlink()


def test_never_points_at_real_local_config():
    assert roster.ROSTER_PATH != _REAL_ROSTER_PATH
    assert "bbc_roster_test_" in str(roster.ROSTER_PATH)


def test_load_missing_returns_empty():
    _reset()
    assert roster.load_roster() == []


def test_load_corrupt_returns_empty():
    _reset()
    roster.ROSTER_PATH.parent.mkdir(exist_ok=True)
    roster.ROSTER_PATH.write_text("{not valid json", encoding="utf-8")
    assert roster.load_roster() == []


def test_add_and_roundtrip():
    _reset()
    added = roster.add_brother(SAMPLE)
    assert added["id"], "expected an id to be assigned"
    assert added["added"], "expected an added date"

    entries = roster.load_roster()
    assert len(entries) == 1
    got = entries[0]
    assert got["name"] == "Atiq Orcbane"
    assert got["archetype"] == "Polearm Backline (Battle Forged)"
    assert got["rating"] == 9.9
    # full snapshot survives the round-trip
    assert got["projected"]["melee_skill"] == 97
    assert got["stars"]["melee_skill"] == 2


def test_ids_are_unique():
    _reset()
    a = roster.add_brother(SAMPLE)
    b = roster.add_brother(SAMPLE)
    assert a["id"] != b["id"], "duplicate names must still get distinct ids"
    assert len(roster.load_roster()) == 2


def test_remove_only_matching_id():
    _reset()
    a = roster.add_brother(dict(SAMPLE, name="Keeper"))
    b = roster.add_brother(dict(SAMPLE, name="Casualty"))

    assert roster.remove_brother(b["id"]) is True
    remaining = roster.load_roster()
    assert len(remaining) == 1
    assert remaining[0]["name"] == "Keeper"
    assert remaining[0]["id"] == a["id"]


def test_remove_unknown_id_returns_false():
    _reset()
    roster.add_brother(SAMPLE)
    assert roster.remove_brother("does-not-exist") is False
    assert len(roster.load_roster()) == 1


def test_add_assigns_sequential_positions():
    _reset()
    a = roster.add_brother(SAMPLE)
    b = roster.add_brother(SAMPLE)
    c = roster.add_brother(SAMPLE)
    assert [a["position"], b["position"], c["position"]] == [0, 1, 2]


def test_first_free_position_reuses_freed_slot():
    _reset()
    roster.add_brother(SAMPLE)              # slot 0
    b = roster.add_brother(SAMPLE)          # slot 1
    roster.add_brother(SAMPLE)              # slot 2
    roster.remove_brother(b["id"])          # frees slot 1
    assert roster.first_free_position(roster.load_roster()) == 1
    # the next hire fills the gap rather than appending at 3
    assert roster.add_brother(SAMPLE)["position"] == 1


def test_first_free_position_none_when_full():
    _reset()
    entries = [{"id": str(i), "position": i} for i in range(roster.GRID_SLOTS)]
    assert roster.first_free_position(entries) is None


def test_set_position_moves_into_empty_slot():
    _reset()
    a = roster.add_brother(SAMPLE)  # slot 0
    assert roster.set_position(a["id"], 14) is True
    assert roster.load_roster()[0]["position"] == 14


def test_set_position_swaps_when_target_occupied():
    _reset()
    a = roster.add_brother(dict(SAMPLE, name="A"))  # slot 0
    b = roster.add_brother(dict(SAMPLE, name="B"))  # slot 1

    roster.set_position(a["id"], 1)  # onto B

    by_name = {e["name"]: e["position"] for e in roster.load_roster()}
    assert by_name["A"] == 1, "A should have moved onto B's slot"
    assert by_name["B"] == 0, "B should have swapped back into A's old slot"


def test_set_position_unknown_id_returns_false():
    _reset()
    assert roster.set_position("nope", 3) is False


def test_ensure_positions_backfills_legacy_entries():
    _reset()
    # a roster.json written before positions existed: no "position" key
    roster.save_roster([
        {"id": "x", "name": "Old One"},
        {"id": "y", "name": "Old Two"},
    ])
    roster.ensure_positions(roster.load_roster())

    positions = sorted(e["position"] for e in roster.load_roster())
    assert positions == [0, 1], f"expected backfilled slots, got {positions}"


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = []
    try:
        for test in tests:
            try:
                test()
                print(f"PASS  {test.__name__}")
            except AssertionError as exc:
                failures.append(test.__name__)
                print(f"FAIL  {test.__name__}: {exc}")
    finally:
        shutil.rmtree(_TMP, ignore_errors=True)
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
