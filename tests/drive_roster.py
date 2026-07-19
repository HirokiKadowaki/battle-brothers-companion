"""End-to-end drive of the roster flow through the real GUI:
evaluate -> Add to Roster dialog -> Roster window -> remove.

Redirects the roster store to a temp dir so the user's real roster is untouched.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bbcompanion  # noqa: F401  (DPI awareness before QApplication)
from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication, QLineEdit, QPushButton

app = QApplication(sys.argv)

from bbcompanion import roster
from bbcompanion.gui import DARK_STYLESHEET, RecruitWindow, build_dark_palette
from bbcompanion.roster_window import RosterWindow

_TMP = Path(tempfile.mkdtemp(prefix="bbc_roster_drive_"))
roster.ROSTERS_PATH = _TMP / "rosters.json"
roster.LEGACY_ROSTER_PATH = _TMP / "roster.json"

# Guard BEFORE writing anything, and assert on the attributes the module itself
# reads. Patching a constant the module no longer uses silently no-ops, and a
# "write then check" guard would already have eaten the real roster by the time
# it fired — both of which happened during development.
for _attr in ("ROSTERS_PATH", "LEGACY_ROSTER_PATH"):
    _path = getattr(roster, _attr)
    if _TMP not in _path.parents:
        raise SystemExit(
            f"ABORT: roster.{_attr} is {_path}, not redirected into the temp dir. "
            "Refusing to run against real user data."
        )

app.setStyle("Fusion")
app.setPalette(build_dark_palette())
app.setStyleSheet(DARK_STYLESHEET)

win = RecruitWindow()
win.show()
app.processEvents()

print("add button enabled before evaluating:", win.add_roster_btn.isEnabled(), "(want False)")

for stat, val in {
    "hp": 60, "fatigue": 100, "resolve": 45, "initiative": 110,
    "melee_skill": 67, "ranged_skill": 52, "melee_defense": 13, "ranged_defense": 13,
}.items():
    win.stat_current_boxes[stat].setValue(val)
win.background_combo.setCurrentText("Sellsword")
win.star_stat_combos[0].setCurrentText("Melee Skill")
win.star_count_boxes[0].setValue(2)
win.on_evaluate()
app.processEvents()
print("add button enabled after evaluating:", win.add_roster_btn.isEnabled(), "(want True)")

selected = win.archetype_table.selectedItems()
print("best-fit archetype auto-selected:", selected[0].text())


def fill_add_dialog():
    dlg = app.activeModalWidget()
    if dlg is None:
        print("!! no modal dialog appeared")
        return
    dlg.findChild(QLineEdit).setText("Atiq Orcbane")
    combo = dlg.findChildren(type(win.background_combo))[0]
    print("dialog archetype defaulted to:", combo.currentText())
    for btn in dlg.findChildren(QPushButton):
        if btn.text() == "Add":
            btn.click()
            return


QTimer.singleShot(400, fill_add_dialog)
win.on_add_to_roster()  # blocks on exec_() until the timer accepts it
app.processEvents()

entries = roster.load_roster()
print("\n--- roster after add ---")
print("entries:", len(entries))
e = entries[0]
print(f"  name={e['name']!r} background={e['background']!r}")
print(f"  archetype={e['archetype']!r} verdict={e['verdict']} rating={e['rating']}")
print(f"  projected melee_skill={e['projected']['melee_skill']} stars={e['stars']}")
print(f"  id set: {bool(e.get('id'))}, added: {e.get('added')}")

# Roster window renders it
rw = RosterWindow(win._guidance_by_name, win)
rw.show()
app.processEvents()
print("\n--- roster window ---")
print("rows:", rw.table.rowCount(), "| empty label visible:", rw.empty_label.isVisible())
print("row0:", [rw.table.item(0, i).text() for i in range(4)])
rw.table.selectRow(0)
app.processEvents()
detail = rw.detail.toPlainText()
print("detail has projected stats:", "Projected at level 11" in detail)
print("detail has build guidance:", "Key perks" in detail)
print("remove button enabled on selection:", rw.remove_btn.isEnabled())

print("\n--- formation grid ---")
print("tiles:", len(rw.tiles), f"(want {roster.GRID_SLOTS})")
print("brother auto-placed at slot:", e["position"], "(want 0)")
print("tile 0 occupied:", rw.tiles[0].entry is not None, "| tile 1 occupied:", rw.tiles[1].entry is not None)

# start from a clean deselected state (the table checks above left him selected)
rw._select(None)

# click his tile -> picks him up
rw._on_tile_clicked(0)
print("click tile -> selected:", rw._selected_id == e["id"], "| tile highlighted:", rw.tiles[0].selected)
print("table row synced to grid selection:", bool(rw.table.selectedItems()))

# click the held tile again -> toggles him off
rw._on_tile_clicked(0)
print("click held tile again -> deselected:", rw._selected_id is None)

# pick up again, then click an empty slot -> moves
rw._on_tile_clicked(0)
rw._on_tile_clicked(11)
app.processEvents()
print("held + click empty slot 11 -> moved to:", roster.load_roster()[0]["position"], "(want 11)")
print("tile 11 now occupied:", rw.tiles[11].entry is not None, "| tile 0 empty:", rw.tiles[0].entry is None)

# swap: add a second brother, then drop him onto the occupied slot
second = roster.add_brother({"name": "Hans", "background": "Militia", "archetype": "Archer",
                             "verdict": "marginal", "rating": 7.0, "current_stats": {},
                             "stars": {}, "projected": {}})
rw.refresh()
hans_slot = second["position"]
print("second brother placed at slot:", hans_slot, "(first free)")
rw._select(second["id"])
rw._on_tile_clicked(11)  # drop Hans onto Atiq
app.processEvents()
by_name = {x["name"]: x["position"] for x in roster.load_roster()}
print("after swap ->", by_name)
print(f"  Hans took slot 11: {by_name['Hans'] == 11} | Atiq swapped back to {hans_slot}: {by_name['Atiq Orcbane'] == hans_slot}")

# Regression: removing the *selected* brother used to re-enter refresh() while
# the table was mid-rebuild and hard-crash Qt (0xc0000374). Drive the real
# button path with the confirmation auto-accepted.
print("\n--- remove selected brother (crash regression) ---")
from PyQt5.QtWidgets import QMessageBox

QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

remaining = roster.load_roster()
rw._select(remaining[0]["id"])
app.processEvents()
print("selected before remove:", rw._selected_id is not None)
rw._on_remove()          # would crash before the fix
app.processEvents()
print("survived removing selected brother:", True)
print("rows now:", rw.table.rowCount(), "| selection cleared:", rw._selected_id is None)

# The original crash: entries removed underneath a populated, selected table,
# then a single refresh() shrinking it. Heap corruption is nondeterministic, so
# this is a smoke test — the real guarantee is the _syncing guard in refresh().
rw._select(None)
roster.add_brother({"name": "Doomed A", "background": "Militia", "archetype": "Archer",
                    "verdict": "poor", "rating": 3.0, "current_stats": {}, "stars": {}, "projected": {}})
roster.add_brother({"name": "Doomed B", "background": "Militia", "archetype": "Archer",
                    "verdict": "poor", "rating": 3.0, "current_stats": {}, "stars": {}, "projected": {}})
rw.refresh()
rw.table.selectRow(0)
app.processEvents()
for x in roster.load_roster():
    roster.remove_brother(x["id"])
rw.refresh()             # 2 populated+selected rows -> 0, the original crash path
app.processEvents()
print("survived bulk removal + shrink refresh:", True)

for x in roster.load_roster():
    rw._select(x["id"])
    rw._on_remove()
    app.processEvents()
print("\n--- after removing everyone ---")
print("rows:", rw.table.rowCount(), "| empty label visible:", rw.empty_label.isVisible())
print("all tiles empty:", all(t.entry is None for t in rw.tiles))

QTimer.singleShot(6000, app.quit)
app.exec_()
shutil.rmtree(_TMP, ignore_errors=True)
