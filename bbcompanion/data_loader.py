import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
# Machine-local state (screen calibration, roster) — gitignored, not shipped data.
LOCAL_CONFIG_DIR = Path(__file__).resolve().parent.parent / "local_config"

STATS = [
    "hp",
    "fatigue",
    "resolve",
    "initiative",
    "melee_skill",
    "ranged_skill",
    "melee_defense",
    "ranged_defense",
]

STAT_LABELS = {
    "hp": "HP",
    "fatigue": "Fatigue",
    "resolve": "Resolve",
    "initiative": "Initiative",
    "melee_skill": "Melee Skill",
    "ranged_skill": "Ranged Skill",
    "melee_defense": "Melee Defense",
    "ranged_defense": "Ranged Defense",
}


def load_backgrounds():
    with open(DATA_DIR / "backgrounds.json", encoding="utf-8") as f:
        return json.load(f)


def load_talents():
    with open(DATA_DIR / "talents.json", encoding="utf-8") as f:
        return json.load(f)


def load_archetypes():
    with open(DATA_DIR / "archetypes.json", encoding="utf-8") as f:
        return json.load(f)["archetypes"]


def load_background_tips():
    """Recommended backgrounds grouped by campaign phase (early/mid/late)."""
    with open(DATA_DIR / "background_tips.json", encoding="utf-8") as f:
        return json.load(f)["phases"]


def load_compositions():
    """Role groups and target company compositions. Returns (roles, presets)."""
    with open(DATA_DIR / "compositions.json", encoding="utf-8") as f:
        data = json.load(f)
    return data["roles"], data["presets"]
