import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

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
