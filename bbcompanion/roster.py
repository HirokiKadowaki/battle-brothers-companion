"""Persistent roster of hired brothers.

Pure data layer (no Qt) backed by local_config/roster.json — machine-local state
alongside the screen calibration, not shipped game data.
"""

import json
import uuid
from datetime import date

from .data_loader import LOCAL_CONFIG_DIR

ROSTER_PATH = LOCAL_CONFIG_DIR / "roster.json"

# Battle formation grid, matching the game's formation screen.
GRID_COLS = 9
GRID_ROWS = 3
GRID_SLOTS = GRID_COLS * GRID_ROWS


def load_roster() -> list:
    """Return the saved brothers, or [] if there is no (readable) roster yet."""
    try:
        with open(ROSTER_PATH, encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        # A missing roster is the normal first-run case; a corrupt one shouldn't
        # take the app down — treat both as empty rather than raising.
        return []
    return entries if isinstance(entries, list) else []


def save_roster(entries: list) -> None:
    ROSTER_PATH.parent.mkdir(exist_ok=True)
    with open(ROSTER_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def first_free_position(entries: list):
    """Lowest unoccupied formation slot, or None if the grid is full."""
    taken = {e.get("position") for e in entries}
    for slot in range(GRID_SLOTS):
        if slot not in taken:
            return slot
    return None


def ensure_positions(entries: list) -> list:
    """Give a formation slot to any brother that lacks one.

    Rosters saved before positions existed have no "position" key; backfill them
    (persisting only if something actually changed) so the grid can show everyone.
    """
    changed = False
    for entry in entries:
        if entry.get("position") is None:
            entry["position"] = first_free_position(entries)
            changed = True
    if changed:
        save_roster(entries)
    return entries


def add_brother(entry: dict) -> dict:
    """Append a brother, assigning a stable id, date, and formation slot."""
    entry = dict(entry)
    entry["id"] = uuid.uuid4().hex
    entry.setdefault("added", date.today().isoformat())
    entries = load_roster()
    entry.setdefault("position", first_free_position(entries))
    entries.append(entry)
    save_roster(entries)
    return entry


def set_position(brother_id: str, position: int) -> bool:
    """Move a brother to a slot, swapping with whoever is already there.

    Swapping (rather than overwriting) keeps click-to-place non-destructive: you
    can never knock a brother off the grid by dropping someone on top of him.
    """
    entries = load_roster()
    mover = next((e for e in entries if e.get("id") == brother_id), None)
    if mover is None:
        return False

    occupant = next(
        (e for e in entries if e.get("position") == position and e is not mover), None
    )
    if occupant is not None:
        occupant["position"] = mover.get("position")
    mover["position"] = position
    save_roster(entries)
    return True


def remove_brother(brother_id: str) -> bool:
    """Remove by id. Returns True if a brother was removed."""
    entries = load_roster()
    remaining = [e for e in entries if e.get("id") != brother_id]
    if len(remaining) == len(entries):
        return False
    save_roster(remaining)
    return True
