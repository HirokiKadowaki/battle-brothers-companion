"""Tests for company-composition comparison.

Custom-preset writes are pinned to a temp dir so the user's real local_config is
never touched (a test in this project previously clobbered real local state).

Run with: python tests/test_composition.py
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbcompanion import composition
from bbcompanion.data_loader import load_archetypes, load_compositions

_REAL_PATH = composition.CUSTOM_PRESETS_PATH
_TMP = Path(tempfile.mkdtemp(prefix="bbc_comp_test_"))
composition.CUSTOM_PRESETS_PATH = _TMP / "compositions.json"

ROLES, PRESETS = load_compositions()


def _brothers(*archetypes):
    return [{"archetype": a} for a in archetypes]


def test_writes_are_redirected_away_from_real_local_config():
    """Checked before any write — see the fuller note in tests/test_roster.py."""
    assert _TMP in composition.CUSTOM_PRESETS_PATH.parents, (
        f"CUSTOM_PRESETS_PATH is {composition.CUSTOM_PRESETS_PATH}, not redirected "
        "into the temp dir — refusing to touch real user data"
    )
    assert composition.CUSTOM_PRESETS_PATH != _REAL_PATH


def test_every_archetype_belongs_to_exactly_one_role():
    """A build missing from the role map would silently vanish from the tally."""
    known = {a["name"] for a in load_archetypes()}
    mapped = [a for role in ROLES for a in role["archetypes"]]

    assert len(mapped) == len(set(mapped)), "an archetype is listed in two roles"
    missing = known - set(mapped)
    assert not missing, f"archetypes not assigned to any role: {sorted(missing)}"
    unknown = set(mapped) - known
    assert not unknown, f"role lists reference unknown archetypes: {sorted(unknown)}"


def test_preset_targets_use_known_role_keys():
    role_keys = {r["key"] for r in ROLES}
    for preset in PRESETS:
        bad = set(preset["targets"]) - role_keys
        assert not bad, f"preset {preset['name']!r} targets unknown roles: {bad}"


def test_preset_archetype_targets_reference_known_archetypes():
    """A per-archetype target naming a build that doesn't exist would silently
    never show — catch typos/renames loudly."""
    known = {a["name"] for a in load_archetypes()}
    for preset in PRESETS:
        for name in preset.get("archetype_targets", {}):
            assert name in known, (
                f"preset {preset['name']!r} targets unknown archetype {name!r}"
            )


def test_preset_archetype_targets_sum_into_role_targets():
    """Where a preset gives both, the per-archetype targets should add up to the
    role totals, so the two views agree."""
    role_of = {a: r["key"] for r in ROLES for a in r["archetypes"]}
    for preset in PRESETS:
        at = preset.get("archetype_targets")
        if not at:
            continue
        summed = {}
        for archetype, n in at.items():
            summed[role_of[archetype]] = summed.get(role_of[archetype], 0) + n
        for key, total in summed.items():
            assert preset["targets"].get(key, 0) == total, (
                f"preset {preset['name']!r}: role '{key}' target "
                f"{preset['targets'].get(key)} != sum of its archetypes {total}"
            )


def test_compare_with_archetype_targets():
    entries = _brothers(
        "2H Hammer Flanker",
        "Dedicated Flank Tank",
        "Dedicated Flank Tank",
    )
    archetype_targets = {"2H Hammer Flanker": 2, "Dedicated Flank Tank": 2, "2H Cleaver / Whip Utility": 1}
    result = composition.compare(
        entries, ROLES, {"frontline": 5}, archetype_targets
    )
    frontline = next(r for r in result["roles"] if r["key"] == "frontline")
    rows = {b["archetype"]: b for b in frontline["breakdown"]}

    assert rows["2H Hammer Flanker"]["count"] == 1
    assert rows["2H Hammer Flanker"]["target"] == 2
    assert rows["2H Hammer Flanker"]["delta"] == -1, "1 of 2 = need 1 more"
    assert rows["Dedicated Flank Tank"]["delta"] == 0, "2 of 2 = on target"
    # An archetype with a target but none hired must still appear, so the gap shows.
    assert "2H Cleaver / Whip Utility" in rows
    assert rows["2H Cleaver / Whip Utility"]["count"] == 0
    assert rows["2H Cleaver / Whip Utility"]["delta"] == -1


def test_compare_without_archetype_targets_unchanged():
    """Presets without archetype_targets must behave exactly as before (breakdown
    rows carry no target key, and zero-count archetypes are omitted)."""
    result = composition.compare(_brothers("Archer"), ROLES, {"ranged": 2})
    ranged = next(r for r in result["roles"] if r["key"] == "ranged")
    assert all("target" not in b for b in ranged["breakdown"])
    assert [b["archetype"] for b in ranged["breakdown"]] == ["Archer"]


def test_compare_counts_and_deltas():
    entries = _brothers(
        "Shield User (Frontline Tank)",
        "Shield User (Frontline Tank)",
        "Shield User (Frontline Tank)",
        "Archer",
        "Sergeant",
    )
    targets = {"frontline": 2, "backline_melee": 3, "ranged": 2, "support": 1}
    result = composition.compare(entries, ROLES, targets)
    by_key = {r["key"]: r for r in result["roles"]}

    assert by_key["frontline"]["have"] == 3
    assert by_key["frontline"]["delta"] == 1, "3 frontline vs target 2 = over by 1"
    assert by_key["backline_melee"]["have"] == 0
    assert by_key["backline_melee"]["delta"] == -3, "none vs target 3 = short by 3"
    assert by_key["support"]["delta"] == 0
    assert result["total"] == 5


def test_compare_reports_archetype_breakdown():
    """The point of the feature: seeing you're shield-user heavy."""
    entries = _brothers(
        "Shield User (Frontline Tank)",
        "Shield User (Frontline Tank)",
        "Two-Handed Battle Forged Frontline",
    )
    result = composition.compare(entries, ROLES, {"frontline": 3})
    frontline = next(r for r in result["roles"] if r["key"] == "frontline")
    breakdown = {b["archetype"]: b["count"] for b in frontline["breakdown"]}

    assert breakdown["Shield User (Frontline Tank)"] == 2
    assert breakdown["Two-Handed Battle Forged Frontline"] == 1


def test_compare_flags_unassigned_archetypes():
    result = composition.compare(_brothers("Something Removed"), ROLES, {})
    assert result["unassigned"] == 1


def test_role_of_archetype():
    assert composition.role_of_archetype(ROLES, "Archer") == "ranged"
    assert composition.role_of_archetype(ROLES, "Sergeant") == "support"
    assert composition.role_of_archetype(ROLES, "Nonexistent") is None


def test_custom_preset_roundtrip_and_replace():
    targets = {"frontline": 7, "backline_melee": 2, "ranged": 2, "support": 1}
    composition.save_custom_preset("My Company", targets)
    saved = composition.load_custom_presets()
    assert len(saved) == 1
    assert saved[0]["targets"]["frontline"] == 7

    # saving the same name replaces rather than duplicating
    composition.save_custom_preset("My Company", dict(targets, frontline=4))
    saved = composition.load_custom_presets()
    assert len(saved) == 1, "same-named preset should be replaced, not duplicated"
    assert saved[0]["targets"]["frontline"] == 4


def test_load_custom_presets_handles_missing_and_corrupt():
    if composition.CUSTOM_PRESETS_PATH.exists():
        composition.CUSTOM_PRESETS_PATH.unlink()
    assert composition.load_custom_presets() == []

    composition.CUSTOM_PRESETS_PATH.parent.mkdir(exist_ok=True)
    composition.CUSTOM_PRESETS_PATH.write_text("{oops", encoding="utf-8")
    assert composition.load_custom_presets() == []


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
