"""Persistent rosters of hired brothers, one per campaign.

Pure data layer (no Qt) backed by local_config/rosters.json — machine-local
state alongside the screen calibration, not shipped game data.

Campaigns live in a single store keyed by name rather than one file each, so a
campaign can be called anything without sanitising it into a filename.
"""

import json
import uuid
from datetime import date

from .data_loader import LOCAL_CONFIG_DIR

ROSTERS_PATH = LOCAL_CONFIG_DIR / "rosters.json"
# Pre-campaign single roster; migrated into the store on first load.
LEGACY_ROSTER_PATH = LOCAL_CONFIG_DIR / "roster.json"
DEFAULT_CAMPAIGN = "Default"

# Battle formation grid, matching the game's formation screen.
GRID_COLS = 9
GRID_ROWS = 3
GRID_SLOTS = GRID_COLS * GRID_ROWS


def _empty_store() -> dict:
    return {"active": DEFAULT_CAMPAIGN, "campaigns": {DEFAULT_CAMPAIGN: []}}


def _load_store() -> dict:
    try:
        with open(ROSTERS_PATH, encoding="utf-8") as f:
            store = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        store = None

    if not isinstance(store, dict) or not isinstance(store.get("campaigns"), dict):
        store = _migrate_legacy() or _empty_store()

    if not store["campaigns"]:
        store["campaigns"][DEFAULT_CAMPAIGN] = []
    if store.get("active") not in store["campaigns"]:
        store["active"] = next(iter(store["campaigns"]))
    return store


def _migrate_legacy():
    """Fold a pre-campaign local_config/roster.json into a Default campaign so
    an existing roster isn't lost when upgrading."""
    try:
        with open(LEGACY_ROSTER_PATH, encoding="utf-8") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(entries, list):
        return None
    store = {"active": DEFAULT_CAMPAIGN, "campaigns": {DEFAULT_CAMPAIGN: entries}}
    _save_store(store)
    return store


def _save_store(store: dict) -> None:
    ROSTERS_PATH.parent.mkdir(exist_ok=True)
    with open(ROSTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


def list_campaigns() -> list:
    return sorted(_load_store()["campaigns"])


def active_campaign() -> str:
    return _load_store()["active"]


def set_active_campaign(name: str) -> bool:
    store = _load_store()
    if name not in store["campaigns"]:
        return False
    store["active"] = name
    _save_store(store)
    return True


def create_campaign(name: str) -> bool:
    """Create an empty campaign and make it active. False if the name is taken."""
    name = name.strip()
    store = _load_store()
    if not name or name in store["campaigns"]:
        return False
    store["campaigns"][name] = []
    store["active"] = name
    _save_store(store)
    return True


def rename_campaign(old: str, new: str) -> bool:
    new = new.strip()
    store = _load_store()
    if old not in store["campaigns"] or not new or new in store["campaigns"]:
        return False
    store["campaigns"][new] = store["campaigns"].pop(old)
    if store["active"] == old:
        store["active"] = new
    _save_store(store)
    return True


def delete_campaign(name: str) -> bool:
    """Delete a campaign. Refuses to remove the last one so there's always a roster."""
    store = _load_store()
    if name not in store["campaigns"] or len(store["campaigns"]) <= 1:
        return False
    del store["campaigns"][name]
    if store["active"] == name:
        store["active"] = next(iter(store["campaigns"]))
    _save_store(store)
    return True


def load_roster() -> list:
    """Brothers in the active campaign ([] if none saved yet)."""
    store = _load_store()
    entries = store["campaigns"].get(store["active"], [])
    return entries if isinstance(entries, list) else []


def save_roster(entries: list) -> None:
    store = _load_store()
    store["campaigns"][store["active"]] = entries
    _save_store(store)


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
