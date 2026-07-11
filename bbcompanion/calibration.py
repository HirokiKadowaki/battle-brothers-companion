import json
import time
from pathlib import Path

import mss
from PIL import Image
from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox

from .data_loader import STAT_LABELS, STATS

LOCAL_CONFIG_DIR = Path(__file__).resolve().parent.parent / "local_config"
SCREEN_REGIONS_PATH = LOCAL_CONFIG_DIR / "screen_regions.json"
STAR_TEMPLATE_PATH = LOCAL_CONFIG_DIR / "star_template.png"


def screen_regions_exist() -> bool:
    return SCREEN_REGIONS_PATH.exists() and STAR_TEMPLATE_PATH.exists()


def load_screen_regions() -> dict:
    with open(SCREEN_REGIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _build_steps():
    steps = [
        {
            "key": "star_template",
            "instruction": "Draw a TIGHT box around ONE filled star icon\n"
            "(pick any stat on the hire screen that currently shows a star)",
            "kind": "template",
        },
        {
            "key": "background_name",
            "instruction": "Draw a box around the recruit's Background name text",
            "kind": "region",
        },
    ]
    for stat in STATS:
        label = STAT_LABELS[stat]
        steps.append(
            {
                "key": f"{stat}_value",
                "instruction": f"Draw a box around the {label} numeric value",
                "kind": "region",
            }
        )
        steps.append(
            {
                "key": f"{stat}_stars",
                "instruction": f"Draw a box around where star icons appear next to {label}\n"
                "(mark the slot even if this recruit has no stars there)",
                "kind": "region",
            }
        )
    return steps


class CalibrationWizard(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setGeometry(self._virtual_desktop_rect())

        self.steps = _build_steps()
        self.step_index = 0
        self.regions = {}
        self._drag_start = None
        self._current_rect = QRect()
        self._confirmed_rect = None

        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    @staticmethod
    def _virtual_desktop_rect() -> QRect:
        rect = QRect()
        for screen in QApplication.screens():
            rect = rect.united(screen.geometry())
        return rect

    def _current_step(self):
        return self.steps[self.step_index]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))

        rect_to_draw = self._confirmed_rect or self._current_rect
        if rect_to_draw and not rect_to_draw.isNull():
            painter.setPen(QPen(QColor(255, 210, 60), 2))
            painter.setBrush(QColor(255, 210, 60, 40))
            painter.drawRect(rect_to_draw)

        step = self._current_step()
        banner = QRect(self.rect().x() + 40, self.rect().y() + 30, self.rect().width() - 80, 90)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 230))
        painter.drawRoundedRect(banner, 8, 8)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        header = f"Calibration step {self.step_index + 1}/{len(self.steps)}"
        painter.drawText(banner.adjusted(16, 8, -16, -46), Qt.AlignLeft | Qt.TextWordWrap, header)

        painter.setFont(QFont("Segoe UI", 10))
        body = step["instruction"]
        if self._confirmed_rect:
            body += "\n\nPress Enter to confirm, Backspace to redraw, Esc to cancel."
        else:
            body += "\n\nClick and drag to draw the box. Esc to cancel."
        painter.drawText(banner.adjusted(16, 34, -16, -8), Qt.AlignLeft | Qt.TextWordWrap, body)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_start = event.pos()
            self._confirmed_rect = None
            self._current_rect = QRect(self._drag_start, self._drag_start)
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            self._current_rect = QRect(self._drag_start, event.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._drag_start is not None:
            self._current_rect = QRect(self._drag_start, event.pos()).normalized()
            self._drag_start = None
            if self._current_rect.width() > 3 and self._current_rect.height() > 3:
                self._confirmed_rect = QRect(self._current_rect)
            self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
        elif event.key() == Qt.Key_Backspace:
            self._confirmed_rect = None
            self._current_rect = QRect()
            self.update()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and self._confirmed_rect:
            self._finalize_step()

    def _finalize_step(self):
        step = self._current_step()
        top_left = self.mapToGlobal(self._confirmed_rect.topLeft())
        box = {
            "x": top_left.x(),
            "y": top_left.y(),
            "w": self._confirmed_rect.width(),
            "h": self._confirmed_rect.height(),
        }

        if step["kind"] == "template":
            self.hide()
            QApplication.processEvents()
            time.sleep(0.15)
            self._capture_star_template(box)
            self.show()
        else:
            self.regions[step["key"]] = box

        self._confirmed_rect = None
        self._current_rect = QRect()
        self.step_index += 1

        if self.step_index >= len(self.steps):
            self._save_and_close()
        else:
            self.update()

    def _capture_star_template(self, box):
        LOCAL_CONFIG_DIR.mkdir(exist_ok=True)
        with mss.mss() as sct:
            monitor = {"left": box["x"], "top": box["y"], "width": box["w"], "height": box["h"]}
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(STAR_TEMPLATE_PATH)

    def _save_and_close(self):
        LOCAL_CONFIG_DIR.mkdir(exist_ok=True)
        with open(SCREEN_REGIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(self.regions, f, indent=2)
        self.accept()


def run_calibration_wizard(parent=None) -> bool:
    wizard = CalibrationWizard(parent)
    result = wizard.exec_()
    if result == QDialog.Accepted:
        QMessageBox.information(parent, "Calibration Complete", "Screen regions saved. You can now use Ctrl+Alt+R to auto-fill a recruit.")
        return True
    return False
