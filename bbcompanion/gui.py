import sys
import time
from pathlib import Path

import mss
from PyQt5.QtCore import Qt, QObject, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import calibration, roster, screen_reader
from .calculator import RecruitCalculator
from .data_loader import STATS, STAT_LABELS, load_background_tips

TOGGLE_HOTKEY = "ctrl+alt+b"
CAPTURE_HOTKEY = "ctrl+alt+r"
LOW_CONFIDENCE_THRESHOLD = 0.6
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
    selection-background-color: #6495ed;
    selection-color: #10151c;
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


LOW_CONFIDENCE_STYLE = "border: 2px solid #e53935; background-color: rgba(120, 30, 30, 230);"


class HotkeyBridge(QObject):
    toggle_signal = pyqtSignal()
    capture_signal = pyqtSignal()


class RecruitWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.calc = RecruitCalculator()
        self.stat_current_boxes = {}
        self.star_stat_combos = []
        self.star_count_boxes = []
        self._last_evaluation = None
        # Non-modal windows must be kept referenced or Qt garbage-collects them
        # the moment the opening method returns.
        self._roster_window = None
        self._tips_window = None
        self._guidance_by_name = {a["name"]: a.get("guidance") for a in self.calc.archetypes}

        # Which campaign phase(s) each background is a recommended hire for.
        self._background_phases = load_background_tips()
        self._phases_by_background = {}
        for phase in self._background_phases:
            for bg_name in phase["backgrounds"]:
                self._phases_by_background.setdefault(bg_name, []).append(phase["label"])

        self.setWindowTitle("Battle Brothers Recruit Potential Calculator")
        # A real window frame (not Qt.Tool) so it gets minimise/close buttons and
        # a taskbar entry — Tool windows have neither, which left no way to get
        # the overlay out of the way of other apps.
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowCloseButtonHint
            | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.resize(760, 640)

        central = BackgroundWidget(BACKGROUND_IMAGE)
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        root.addWidget(self._build_input_panel())
        root.addWidget(self._build_results_panel())

        button_row = QHBoxLayout()
        evaluate_btn = QPushButton("Evaluate Recruit")
        evaluate_btn.clicked.connect(self.on_evaluate)
        button_row.addWidget(evaluate_btn)

        capture_btn = QPushButton(f"Read Recruit From Screen ({CAPTURE_HOTKEY})")
        capture_btn.clicked.connect(self.capture_and_fill)
        button_row.addWidget(capture_btn)

        self.add_roster_btn = QPushButton("Add to Roster...")
        self.add_roster_btn.clicked.connect(self.on_add_to_roster)
        self.add_roster_btn.setEnabled(False)  # needs an evaluation to snapshot
        self.add_roster_btn.setToolTip("Evaluate a recruit first")
        button_row.addWidget(self.add_roster_btn)

        roster_btn = QPushButton("Roster...")
        roster_btn.clicked.connect(self.on_open_roster)
        button_row.addWidget(roster_btn)

        tips_btn = QPushButton("Background Tips...")
        tips_btn.clicked.connect(self.on_background_tips)
        button_row.addWidget(tips_btn)

        calibrate_btn = QPushButton("Calibrate Stats Panel...")
        calibrate_btn.clicked.connect(self.on_calibrate)
        button_row.addWidget(calibrate_btn)

        self.on_top_check = QCheckBox("Stay on top")
        self.on_top_check.setChecked(True)
        self.on_top_check.setToolTip("Uncheck to let other windows (e.g. a browser) cover this one")
        self.on_top_check.toggled.connect(self.on_toggle_always_on_top)
        button_row.addWidget(self.on_top_check)
        root.addLayout(button_row)

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
        # Qt's default popup uses the private QComboBoxListView, whose item
        # painting swallows the selection highlight once the app stylesheet is
        # applied — so type-to-jump (press "G" -> Gambler) landed on a row that
        # looked identical to every other. A plain QListView paints it properly.
        self.background_combo.setView(QListView())
        self.background_combo.currentTextChanged.connect(self._update_background_phase_note)
        layout.addWidget(self.background_combo, 0, 1, 1, 2)

        self.background_phase_label = QLabel("")
        self.background_phase_label.setStyleSheet("color: #b0bec5; font-style: italic;")
        layout.addWidget(self.background_phase_label, 0, 3)
        self._update_background_phase_note(self.background_combo.currentText())

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

        layout.addWidget(QLabel("Build Archetype Fit  (click a row for perks & priorities)"))
        self.archetype_table = QTableWidget(0, 4)
        self.archetype_table.setHorizontalHeaderLabels(["Archetype", "Verdict", "Score", "Limiting Stat(s)"])
        self.archetype_table.horizontalHeader().setStretchLastSection(True)
        self.archetype_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.archetype_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.archetype_table.itemSelectionChanged.connect(self.on_archetype_selected)
        layout.addWidget(self.archetype_table)

        self.archetype_detail = QTextBrowser()
        self.archetype_detail.setMinimumHeight(150)
        self.archetype_detail.setPlaceholderText("Select an archetype above to see how to build it.")
        layout.addWidget(self.archetype_detail)

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

        # Kept so "Add to Roster" can snapshot this evaluation without recomputing.
        self._last_evaluation = {
            "background": background,
            "current_stats": current_stats,
            "stars": star_assignments,
            "projected": {p.stat: p.projected for p in projections},
            "fits": {f.name: f for f in fits},
        }
        self.add_roster_btn.setEnabled(True)

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
            score_item = QTableWidgetItem(f"{fit.rating:.1f}/10")
            score_item.setTextAlignment(Qt.AlignCenter)
            self.archetype_table.setItem(row, 2, score_item)
            limiting = ", ".join(STAT_LABELS[s] for s in fit.limiting_stats) or "-"
            self.archetype_table.setItem(row, 3, QTableWidgetItem(limiting))

        self._set_overall_verdict(overall, fits)

        # Show the best-fit build's guidance right away (fits are ranked best-first).
        if fits:
            self.archetype_table.selectRow(0)

    def _update_background_phase_note(self, background_name: str):
        phases = self._phases_by_background.get(background_name)
        self.background_phase_label.setText(
            f"{' / '.join(phases)} pick" if phases else "—"
        )

    def on_add_to_roster(self):
        if not self._last_evaluation:
            return
        evaluation = self._last_evaluation

        # Default to whichever archetype is selected in the results table (which
        # auto-selects the best fit after an evaluation).
        selected = self.archetype_table.selectedItems()
        default_archetype = (
            self.archetype_table.item(selected[0].row(), 0).text() if selected else ""
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Add to Roster")
        dialog.resize(420, 170)
        layout = QGridLayout(dialog)

        layout.addWidget(QLabel("Name:"), 0, 0)
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. Atiq Orcbane")
        layout.addWidget(name_edit, 0, 1)

        layout.addWidget(QLabel("Building toward:"), 1, 0)
        archetype_combo = QComboBox()
        archetype_combo.addItems([a["name"] for a in self.calc.archetypes])
        if default_archetype:
            archetype_combo.setCurrentText(default_archetype)
        layout.addWidget(archetype_combo, 1, 1)

        fit_label = QLabel()
        fit_label.setStyleSheet("color: #b0bec5;")
        layout.addWidget(fit_label, 2, 1)

        def update_fit(archetype_name):
            fit = evaluation["fits"].get(archetype_name)
            if fit:
                verdict_text = VERDICT_STYLE[fit.verdict][0]
                fit_label.setText(f"{verdict_text} · {fit.rating:.1f}/10 for this recruit")
            else:
                fit_label.setText("")

        archetype_combo.currentTextChanged.connect(update_fit)
        update_fit(archetype_combo.currentText())

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dialog.reject)
        buttons.addWidget(cancel_btn)
        save_btn = QPushButton("Add")
        save_btn.setDefault(True)
        save_btn.clicked.connect(dialog.accept)
        buttons.addWidget(save_btn)
        layout.addLayout(buttons, 3, 0, 1, 2)

        name_edit.setFocus()
        if dialog.exec_() != QDialog.Accepted:
            return

        name = name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Name Needed", "Give the brother a name so you can find him in the roster.")
            self.on_add_to_roster()  # re-prompt rather than saving a nameless entry
            return

        archetype_name = archetype_combo.currentText()
        fit = evaluation["fits"].get(archetype_name)
        roster.add_brother(
            {
                "name": name,
                "background": evaluation["background"],
                "archetype": archetype_name,
                "verdict": fit.verdict if fit else None,
                "rating": fit.rating if fit else 0.0,
                "current_stats": evaluation["current_stats"],
                "stars": evaluation["stars"],
                "projected": evaluation["projected"],
            }
        )
        # If the roster is already open alongside us, show the new brother at once.
        if self._roster_window is not None and self._roster_window.isVisible():
            self._roster_window.refresh()

        self.verdict_label.setText(f"{name} added to the roster as {archetype_name}.")
        self.verdict_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 6px; color: white; background-color: #2e7d32;"
        )

    def on_open_roster(self):
        # Imported here to avoid a circular import: roster_window reuses this
        # module's BackgroundWidget/VERDICT_STYLE.
        from .roster_window import RosterWindow

        if self._roster_window is None:
            self._roster_window = RosterWindow(self._guidance_by_name, self)
        self._roster_window.refresh()
        self._show_tool_window(self._roster_window)

    def on_background_tips(self):
        if self._tips_window is None:
            sections = []
            for phase in self._background_phases:
                names = ", ".join(phase["backgrounds"])
                sections.append(
                    f'<h3 style="margin:8px 0 2px 0;">{phase["label"]}</h3>'
                    f'<p style="margin:0 0 2px 0; color:#b0bec5;"><i>{phase.get("hint", "")}</i></p>'
                    f'<p style="margin:0;">{names}</p>'
                )
            dialog = QDialog(self)
            dialog.setWindowTitle("Background Tips")
            dialog.resize(460, 420)
            layout = QVBoxLayout(dialog)
            browser = QTextBrowser()
            browser.setHtml(
                "".join(sections)
                + '<p style="margin-top:10px; color:#90a4ae; font-size:11px;">'
                "Rough guide only — a great roll on a cheap background still beats "
                "a bad roll on an expensive one.</p>"
            )
            layout.addWidget(browser)
            close_btn = QPushButton("Close")
            close_btn.clicked.connect(dialog.hide)
            layout.addWidget(close_btn)
            self._tips_window = dialog
        self._show_tool_window(self._tips_window)

    @staticmethod
    def _show_tool_window(window):
        """Show a companion window non-modally, so the main window and the other
        companion windows all stay usable alongside it."""
        window.show()
        window.raise_()
        window.activateWindow()

    def on_archetype_selected(self):
        items = self.archetype_table.selectedItems()
        if not items:
            return
        name_item = self.archetype_table.item(items[0].row(), 0)
        if name_item is None:
            return
        name = name_item.text()
        guidance = self._guidance_by_name.get(name)
        if not guidance:
            self.archetype_detail.setHtml(f"<b>{name}</b><br>No build guidance available.")
            return

        def pretty(token):
            for key, label in STAT_LABELS.items():
                token = token.replace(key, label)
            return token

        priorities = " &rarr; ".join(pretty(t) for t in guidance["level_up_priority"])
        perks = ", ".join(guidance["key_perks"])
        weapons = ", ".join(guidance["weapons"])
        backgrounds = guidance.get("backgrounds")
        backgrounds_html = (
            f'<p style="margin:2px 0;"><b>Best backgrounds:</b> {", ".join(backgrounds)}</p>'
            if backgrounds
            else ""
        )
        self.archetype_detail.setHtml(
            f'<h3 style="margin:2px 0;">{name}</h3>'
            f'<p style="margin:2px 0;">{guidance["playstyle"]}</p>'
            f'<p style="margin:6px 0 2px 0;"><b>Level-up priority:</b> {priorities}</p>'
            f'<p style="margin:2px 0;"><b>Key perks:</b> {perks}</p>'
            f'<p style="margin:2px 0;"><b>Weapons / gear:</b> {weapons}</p>'
            f"{backgrounds_html}"
        )

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

    def on_toggle_always_on_top(self, stay_on_top: bool):
        flags = self.windowFlags()
        if stay_on_top:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        # Changing flags re-creates the native window, so it must be re-shown.
        self.show()

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def on_calibrate(self):
        self.hide()
        QApplication.processEvents()
        time.sleep(0.15)
        calibration.run_calibration_wizard(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def _mark_field_confidence(self, widget, confidence: float):
        widget.setStyleSheet(LOW_CONFIDENCE_STYLE if confidence < LOW_CONFIDENCE_THRESHOLD else "")

    def capture_and_fill(self):
        if not calibration.screen_regions_exist():
            QMessageBox.information(
                self,
                "Calibration Needed",
                "The stats panel isn't calibrated yet. Click 'Calibrate Stats Panel...' first "
                "(draw one box around the stats grid), then press Ctrl+Alt+R on a recruit's "
                "character sheet.",
            )
            return

        panel = calibration.load_screen_regions()["panel"]

        for spin in self.stat_current_boxes.values():
            spin.setStyleSheet("")

        was_visible = self.isVisible()
        self.hide()
        # Fully clear this window off the screen before grabbing: the desktop
        # needs time to repaint the game underneath, or our own (dark) window
        # bleeds into the capture over whatever cells it overlapped — which is
        # why top-of-panel cells like HP/Melee Skill would read 0 on repeat
        # captures once the window had been raised to the front.
        for _ in range(10):
            QApplication.processEvents()
            time.sleep(0.03)

        star_hits = []
        try:
            with mss.mss() as sct:
                # One grab of the whole panel, then crop cells from it — avoids
                # 16 separate grabs racing the compositor at different moments.
                panel_img = screen_reader.capture_region(sct, panel)
            panel_img.save(calibration.LOCAL_CONFIG_DIR / "last_capture.png")

            # Snap the 8 rows to the grid actually detected in the capture, so a
            # roughly-drawn calibration box still lines up cell-for-cell.
            boxes = screen_reader.derive_grid_boxes_from_image(panel, panel_img)

            def cell_crop(box):
                x0 = box["x"] - panel["x"]
                y0 = box["y"] - panel["y"]
                return panel_img.crop((x0, y0, x0 + box["w"], y0 + box["h"]))

            for stat in STATS:
                value_box = boxes.get(f"{stat}_value")
                if value_box:
                    result = screen_reader.read_stat_value(cell_crop(value_box))
                    self.stat_current_boxes[stat].setValue(result.value)
                    self._mark_field_confidence(self.stat_current_boxes[stat], result.confidence)

                star_box = boxes.get(f"{stat}_stars")
                if star_box:
                    star_result = screen_reader.count_stars(cell_crop(star_box))
                    if star_result.value > 0:
                        star_hits.append((stat, star_result.value))
        finally:
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()

        # Battle Brothers gives every recruit stars on exactly 3 attributes, so
        # keep at most 3 detected; the user reviews/corrects these regardless.
        star_hits = star_hits[:3]
        for i, (combo, spin) in enumerate(zip(self.star_stat_combos, self.star_count_boxes)):
            if i < len(star_hits):
                stat, count = star_hits[i]
                idx = combo.findText(STAT_LABELS[stat])
                combo.setCurrentIndex(idx if idx >= 0 else 0)
                spin.setValue(count)
            else:
                combo.setCurrentIndex(0)
                spin.setValue(0)

        self.verdict_label.setText(
            "Auto-filled from screen. Background isn't on this panel — set it manually. "
            "Review star counts and any red field, then Evaluate."
        )
        self.verdict_label.setStyleSheet(
            "font-size: 13px; font-weight: bold; padding: 6px; color: white; background-color: #455a64;"
        )


def register_hotkeys(bridge: HotkeyBridge):
    try:
        import keyboard

        keyboard.add_hotkey(TOGGLE_HOTKEY, lambda: bridge.toggle_signal.emit())
        keyboard.add_hotkey(CAPTURE_HOTKEY, lambda: bridge.capture_signal.emit())
        return True
    except Exception as exc:  # global hotkey hook can fail without admin rights on some setups
        print(f"Warning: could not register global hotkeys ({exc}). Use the on-screen buttons instead.")
        return False


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(build_dark_palette())
    app.setStyleSheet(DARK_STYLESHEET)

    window = RecruitWindow()

    bridge = HotkeyBridge()
    bridge.toggle_signal.connect(window.toggle_visibility, Qt.QueuedConnection)
    bridge.capture_signal.connect(window.capture_and_fill, Qt.QueuedConnection)
    register_hotkeys(bridge)

    window.show()
    sys.exit(app.exec_())
