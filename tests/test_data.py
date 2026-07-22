"""Consistency checks across the JSON data files.

These catch typos and renames that would otherwise fail silently in the GUI
(e.g. a background tip that never matches, so the note stays blank).
Run with: python tests/test_data.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bbcompanion.data_loader import (
    STATS,
    load_archetypes,
    load_background_tips,
    load_backgrounds,
)


def test_background_tip_names_exist():
    known = set(load_backgrounds())
    for phase in load_background_tips():
        for name in phase["backgrounds"]:
            assert name in known, (
                f"background_tips.json phase '{phase['key']}' lists '{name}', "
                f"which is not a key in backgrounds.json"
            )


def test_background_tip_phases_wellformed():
    phases = load_background_tips()
    assert len(phases) == 3, f"expected 3 phases, got {len(phases)}"
    assert [p["key"] for p in phases] == ["early", "mid", "late"]
    for phase in phases:
        assert phase.get("label"), f"phase {phase['key']} missing label"
        assert phase["backgrounds"], f"phase {phase['key']} has no backgrounds"


def test_archetype_requirements_use_known_stats():
    for archetype in load_archetypes():
        for req in archetype["requirements"]:
            assert req["stat"] in STATS, f"{archetype['name']} requires unknown stat {req['stat']}"


def test_archetype_guidance_present():
    for archetype in load_archetypes():
        guidance = archetype.get("guidance")
        assert guidance, f"{archetype['name']} has no guidance block"
        for key in ("level_up_priority", "key_perks", "weapons", "playstyle"):
            assert guidance.get(key), f"{archetype['name']} guidance missing {key}"


def test_archetype_guidance_backgrounds_exist():
    """Where an archetype recommends 'best backgrounds', they must be real
    backgrounds — otherwise a typo silently shows a bogus recommendation."""
    known = set(load_backgrounds())
    for archetype in load_archetypes():
        for name in archetype.get("guidance", {}).get("backgrounds", []):
            assert name in known, (
                f"{archetype['name']} recommends background {name!r}, "
                f"which is not in backgrounds.json"
            )


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = []
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures.append(test.__name__)
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
