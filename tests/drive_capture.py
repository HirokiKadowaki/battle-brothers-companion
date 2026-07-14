"""End-to-end test of the single-box capture path through the real GUI.

Points screen_reader.capture_region at the bundled real screenshot (images.jpg)
instead of the live screen, writes a panel-box calibration, then runs
RecruitWindow.capture_and_fill() and checks the populated form.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bbcompanion  # noqa: F401  (DPI awareness before QApplication)
from PIL import Image
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

from bbcompanion import calibration, screen_reader
from bbcompanion.gui import RecruitWindow

# NEVER touch the user's real local_config: redirect calibration paths to a
# throwaway temp dir for the duration of this test.
_TMP = Path(tempfile.mkdtemp(prefix="bbc_test_"))
calibration.LOCAL_CONFIG_DIR = _TMP
calibration.SCREEN_REGIONS_PATH = _TMP / "screen_regions.json"

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT = Image.open(ROOT / "images.jpg").convert("RGB")

# Treat image-pixel coordinates as "screen" coordinates: capture_region just
# crops the screenshot at the requested box.
def fake_capture_region(sct, box):
    return SCREENSHOT.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]))


screen_reader.capture_region = fake_capture_region

# Write a panel-box calibration matching the stats grid in images.jpg.
calibration.SCREEN_REGIONS_PATH.write_text(
    json.dumps({"panel": {"x": 6, "y": 532, "w": 342, "h": 241}})
)

win = RecruitWindow()
win.show()
app.processEvents()
win.capture_and_fill()
app.processEvents()

expected = {
    "hp": 59, "fatigue": 104, "resolve": 44, "initiative": 102,
    "melee_skill": 46, "ranged_skill": 40, "melee_defense": 1, "ranged_defense": 5,
}
print("--- values ---")
ok = 0
for stat, box in win.stat_current_boxes.items():
    got = box.value()
    flag = "OK" if got == expected[stat] else f"X (exp {expected[stat]})"
    if got == expected[stat]:
        ok += 1
    print(f"  {stat:15} {got:5}  {flag}")
print(f"values correct: {ok}/8")

print("--- stars ---")
for combo, spin in zip(win.star_stat_combos, win.star_count_boxes):
    if combo.currentText() != "-- none --":
        print(f"  {combo.currentText()}: {spin.value()}")

# cleanup the throwaway temp dir
import shutil
shutil.rmtree(_TMP, ignore_errors=True)
