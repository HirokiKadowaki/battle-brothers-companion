"""Drives the CalibrationWizard programmatically against the fixture window
already displayed at screen (0,0), using the same public code path the real
mouse-drag UI uses (_confirmed_rect + _finalize_step), to verify the
calibrate -> save -> capture_and_fill wiring end-to-end without a real game.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bbcompanion  # noqa: F401  (sets QT_ENABLE_HIGHDPI_SCALING before QApplication exists)
from PyQt5.QtCore import QPoint, QRect
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

from bbcompanion.calibration import CalibrationWizard, _build_steps

with open("tests/fixture_layout.json", encoding="utf-8") as f:
    fixture = json.load(f)

boxes = dict(fixture["boxes"])
# Single star from the hp row's star icon, used as the star-matching template.
boxes["star_template"] = [222, 132, 258, 168]

wiz = CalibrationWizard()
wiz.show()
app.processEvents()

steps = _build_steps()
for step in steps:
    key = step["key"]
    x0, y0, x1, y1 = boxes[key]
    p0 = wiz.mapFromGlobal(QPoint(x0, y0))
    p1 = wiz.mapFromGlobal(QPoint(x1, y1))
    wiz._confirmed_rect = QRect(p0, p1).normalized()
    wiz._finalize_step()
    app.processEvents()

print("wizard result:", wiz.result())
print("regions saved:", dict(wiz.regions))
