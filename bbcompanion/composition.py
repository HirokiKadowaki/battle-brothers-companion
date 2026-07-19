"""Compare a roster against a target company composition.

Pure logic + data (no Qt). Ships guide-grounded presets from
data/compositions.json; user-saved presets live in local_config/compositions.json.
"""

import json

from .data_loader import LOCAL_CONFIG_DIR, load_compositions

CUSTOM_PRESETS_PATH = LOCAL_CONFIG_DIR / "compositions.json"


def role_of_archetype(roles: list, archetype: str):
    """Which role group an archetype belongs to, or None if unrecognised."""
    for role in roles:
        if archetype in role["archetypes"]:
            return role["key"]
    return None


def load_custom_presets() -> list:
    try:
        with open(CUSTOM_PRESETS_PATH, encoding="utf-8") as f:
            presets = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return presets if isinstance(presets, list) else []


def save_custom_preset(name: str, targets: dict) -> list:
    """Add or replace a custom preset by name; returns all custom presets."""
    presets = [p for p in load_custom_presets() if p.get("name") != name]
    presets.append({"name": name, "note": "Your saved composition.", "targets": targets, "custom": True})
    CUSTOM_PRESETS_PATH.parent.mkdir(exist_ok=True)
    with open(CUSTOM_PRESETS_PATH, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)
    return presets


def all_presets() -> tuple:
    """(roles, presets) with the user's saved compositions appended."""
    roles, presets = load_compositions()
    return roles, presets + load_custom_presets()


def compare(entries: list, roles: list, targets: dict) -> dict:
    """Tally a roster against target role counts.

    Returns {"roles": [...], "unassigned": int, "total": int}, where each role
    carries its target, actual count, delta, and the per-archetype breakdown of
    who is filling it.
    """
    counts = {}
    for entry in entries:
        archetype = entry.get("archetype")
        counts[archetype] = counts.get(archetype, 0) + 1

    result = []
    accounted = 0
    for role in roles:
        breakdown = [
            {"archetype": a, "count": counts.get(a, 0)}
            for a in role["archetypes"]
            if counts.get(a, 0) > 0
        ]
        have = sum(b["count"] for b in breakdown)
        accounted += have
        target = int(targets.get(role["key"], 0))
        result.append(
            {
                "key": role["key"],
                "label": role["label"],
                "target": target,
                "have": have,
                "delta": have - target,
                "breakdown": breakdown,
            }
        )

    return {
        "roles": result,
        # Brothers whose archetype isn't in any role group (e.g. data renamed).
        "unassigned": len(entries) - accounted,
        "total": len(entries),
    }
