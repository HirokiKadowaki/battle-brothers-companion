import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bbcompanion  # noqa: F401  (sets QT_ENABLE_HIGHDPI_SCALING before QApplication exists)
from PyQt5.QtWidgets import QApplication

app = QApplication(sys.argv)

from bbcompanion.gui import RecruitWindow

win = RecruitWindow()
win.show()
app.processEvents()

win.capture_and_fill()
app.processEvents()

print("background:", win.background_combo.currentText())
for stat, box in win.stat_current_boxes.items():
    print(f"  {stat}: {box.value()}  stylesheet={box.styleSheet()!r}")

print("stars:")
for combo, spin in zip(win.star_stat_combos, win.star_count_boxes):
    print(f"  {combo.currentText()}: {spin.value()}")

print("verdict label:", win.verdict_label.text())
