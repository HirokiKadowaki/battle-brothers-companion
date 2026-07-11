import sys
from pathlib import Path

from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .calculator import RecruitCalculator
from .data_loader import STATS, STAT_LABELS

HOTKEY = "ctrl+alt+b"
BACKGROUND_IMAGE = Path(__file__).resolve().parent.parent / "assets" / "keyvisual.jpg"

VERDICT_STYLE = {
    "good": ("Good Fit", "#2e7d32"),
    "marginal": ("Marginal", "#f9a825"),
    "poor": ("Poor Fit", "#c62828"),
}

DARK_STYLESHEET = """
QGroupBox {
    background-color: rgba(24, 24, 24, 190);
    border: 1px solid #555;
    border-radius: 8px;
    margin-top: 14px;
    color: #eee;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #ddd;
}
QLabel {
    color: #eee;
    background: transparent;
}
QComboBox, QSpinBox {
    background-color: rgba(45, 45, 45, 230);
    color: #eee;
    border: 1px solid #666;
    border-radius: 4px;
    padding: 2px 4px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #eee;
    selection-background-color: #555;
}
QTableWidget {
    background-color: rgba(18, 18, 18, 210);
    color: #eee;
    gridline-color: #555;
    border: 1px solid #555;
}
QHeaderView::section {
    background-color: #333;
    color: #eee;
    border: 1px solid #555;
    padding: 4px;
}
QPushButton {
    background-color: rgba(60, 60, 60, 230);
    color: #eee;
    border: 1px solid #777;
    border-radius: 4px;
    padding: 8px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: rgba(85, 85, 85, 230);
}
QPushButton:pressed {
    background-color: rgba(40, 40, 40, 230);
}
"""


def build_dark_palette() -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(24, 24, 24))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Highlight, QColor(100, 149, 237))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    return palette


class BackgroundWidget(QWidget):
    """Central widget that paints a cover-fit wallpaper with a dark scrim behind the panels."""

    def __init__(self, image_path: Path, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap(str(image_path)) if image_path.exists() else None

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = (scaled.width() - self.width()) // 2
            y = (scaled.height() - self.height()) // 2
            painter.drawPixmap(-x, -y, scaled)
        else:
            painter.fillRect(self.rect(), QColor(24, 24, 24))
        painter.fillRect(self.rect(), QColor(0, 0, 0, 140))
        super().paintEvent(event)


class HotkeyBridge(QObject):
    toggle_signal = pyqtSignal()


class RecruitWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.calc = RecruitCalculator()
        self.stat_current_boxes = {}
        self.star_stat_combos = []
        self.star_count_boxes = []

        self.setWindowTitle("Battle Brothers Recruit Potential Calculator")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(760, 640)

        central = BackgroundWidget(BACKGROUND_IMAGE)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_input_panel())
        root.addWidget(self._build_results_panel())

        evaluate_btn = QPushButton("Evaluate Recruit")
        evaluate_btn.clicked.connect(self.on_evaluate)
        root.addWidget(evaluate_btn)

        self.verdict_label = QLabel("")
        self.verdict_label.setAlignment(Qt.AlignCenter)
        self.verdict_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 6px;")
        root.addWidget(self.verdict_label)

    def _build_input_panel(self):
        box = QGroupBox("Recruit Info")
        layout = QGridLayout(box)

        layout.addWidget(QLabel("Background:"), 0, 0)
        self.background_combo = QComboBox()
        self.background_combo.addItems(self.calc.background_names())
        layout.addWidget(self.background_combo, 0, 1, 1, 3)

        layout.addWidget(QLabel("Current stat rolls"), 1, 0, 1, 4)
        row = 2
        col = 0
        for stat in STATS:
            layout.addWidget(QLabel(STAT_LABELS[stat] + ":"), row, col)
            spin = QSpinBox()
            spin.setRange(-50, 300)
            self.stat_current_boxes[stat] = spin
            layout.addWidget(spin, row, col + 1)
            col += 2
            if col >= 4:
                col = 0
                row += 1

        row += 1
        layout.addWidget(QLabel("Stars (pick the 3 talented attributes):"), row, 0, 1, 4)
        row += 1
        for i in range(3):
            combo = QComboBox()
            combo.addItem("-- none --")
            combo.addItems([STAT_LABELS[s] for s in STATS])
            star_spin = QSpinBox()
            star_spin.setRange(0, 3)
            self.star_stat_combos.append(combo)
            self.star_count_boxes.append(star_spin)
            layout.addWidget(QLabel(f"Star slot {i + 1}:"), row, 0)
            layout.addWidget(combo, row, 1)
            layout.addWidget(QLabel("Stars:"), row, 2)
            layout.addWidget(star_spin, row, 3)
            row += 1

        return box

    def _build_results_panel(self):
        box = QGroupBox("Projected Level 11 Potential")
        layout = QVBoxLayout(box)

        self.stat_table = QTableWidget(0, 5)
        self.stat_table.setHorizontalHeaderLabels(
            ["Stat", "Current", "Stars", "Projected (Lvl 11)", "% of BG Ceiling (current roll)"]
        )
        self.stat_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.stat_table)

        layout.addWidget(QLabel("Build Archetype Fit"))
        self.archetype_table = QTableWidget(0, 3)
        self.archetype_table.setHorizontalHeaderLabels(["Archetype", "Verdict", "Limiting Stat(s)"])
        self.archetype_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.archetype_table)

        return box

    def _label_to_stat(self, label: str):
        for stat in STATS:
            if STAT_LABELS[stat] == label:
                return stat
        return None

    def on_evaluate(self):
        background = self.background_combo.currentText()
        current_stats = {stat: box.value() for stat, box in self.stat_current_boxes.items()}

        star_assignments = {}
        for combo, spin in zip(self.star_stat_combos, self.star_count_boxes):
            label = combo.currentText()
            if label == "-- none --":
                continue
            stat = self._label_to_stat(label)
            if stat:
                star_assignments[stat] = spin.value()

        projections, fits, overall = self.calc.evaluate_recruit(background, current_stats, star_assignments)

        self.stat_table.setRowCount(len(projections))
        for row, proj in enumerate(projections):
            values = [
                STAT_LABELS[proj.stat],
                str(proj.current),
                str(proj.stars),
                str(proj.projected),
                f"{proj.ceiling_pct}%  (range {proj.bg_min}-{proj.bg_max})",
            ]
            for col, val in enumerate(values):
                self.stat_table.setItem(row, col, QTableWidgetItem(val))

        self.archetype_table.setRowCount(len(fits))
        for row, fit in enumerate(fits):
            label, color = VERDICT_STYLE[fit.verdict]
            self.archetype_table.setItem(row, 0, QTableWidgetItem(fit.name))
            verdict_item = QTableWidgetItem(label)
            verdict_item.setForeground(Qt.white)
            verdict_item.setBackground(self._qcolor(color))
            self.archetype_table.setItem(row, 1, verdict_item)
            limiting = ", ".join(STAT_LABELS[s] for s in fit.limiting_stats) or "-"
            self.archetype_table.setItem(row, 2, QTableWidgetItem(limiting))

        self._set_overall_verdict(overall, fits)

    def _qcolor(self, hex_color):
        return QColor(hex_color)

    def _set_overall_verdict(self, overall, fits):
        if overall == "recommend":
            best = [f for f in fits if f.verdict == "good"]
            names = ", ".join(f.name for f in best[:3])
            text = f"RECOMMENDED BUILD(S): {names}"
            color = "#2e7d32"
        elif overall == "marginal":
            best = [f for f in fits if f.verdict == "marginal"]
            names = ", ".join(f.name for f in best[:3])
            text = f"MARGINAL FIT: {names} (check limiting stats)"
            color = "#f9a825"
        else:
            text = "NOT WORTH INVESTING FURTHER — use as cheap filler/backup only"
            color = "#c62828"
        self.verdict_label.setText(text)
        self.verdict_label.setStyleSheet(f"font-size: 16px; font-weight: bold; padding: 6px; color: white; background-color: {color};")

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()


def register_hotkey(bridge: HotkeyBridge):
    try:
        import keyboard

        keyboard.add_hotkey(HOTKEY, lambda: bridge.toggle_signal.emit())
        return True
    except Exception as exc:  # global hotkey hook can fail without admin rights on some setups
        print(f"Warning: could not register global hotkey ({exc}). Use the tray/window directly instead.")
        return False


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())
    app.setStyleSheet(DARK_STYLESHEET)

    window = RecruitWindow()

    bridge = HotkeyBridge()
    bridge.toggle_signal.connect(window.toggle_visibility, Qt.QueuedConnection)
    register_hotkey(bridge)

    window.show()
    sys.exit(app.exec_())
