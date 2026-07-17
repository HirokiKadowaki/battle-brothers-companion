"""The company roster: brothers you've hired and the build you're aiming them at."""

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import roster
from .data_loader import STATS, STAT_LABELS
from .gui import BACKGROUND_IMAGE, VERDICT_STYLE, BackgroundWidget

EMPTY_MESSAGE = "No brothers yet — evaluate a recruit, then use 'Add to Roster...'"
PLACE_HINT = "Click a brother, then click a slot to move him (swaps if the slot is taken)."

TILE_W, TILE_H = 74, 78
SELECTED_COLOR = QColor(120, 190, 255)


def _pretty_stat_tokens(token: str) -> str:
    for key, label in STAT_LABELS.items():
        token = token.replace(key, label)
    return token


class SlotTile(QFrame):
    """One formation slot: a painted silhouette (no game art) plus the name.

    Empty slots show a dim silhouette; occupied ones are brighter, named, and
    bordered in their fit-verdict colour.
    """

    clicked = pyqtSignal(int)

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.entry = None
        self.selected = False
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.PointingHandCursor)

    def set_entry(self, entry):
        self.entry = entry
        self.setToolTip(
            f"{entry['name']} — {entry.get('archetype', '-')}" if entry else "Empty slot"
        )
        self.update()

    def set_selected(self, selected: bool):
        if self.selected != selected:
            self.selected = selected
            self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        occupied = self.entry is not None

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(38, 33, 28) if occupied else QColor(26, 23, 20, 200))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

        # Silhouette: head + shoulders, centred in the upper part of the tile.
        silhouette = QColor(150, 150, 150) if occupied else QColor(58, 52, 46)
        painter.setBrush(silhouette)
        cx, top = self.width() / 2, 12.0
        painter.drawEllipse(QRectF(cx - 9, top, 18, 18))
        shoulders = QPainterPath()
        shoulders.moveTo(cx - 19, top + 44)
        shoulders.cubicTo(cx - 19, top + 24, cx + 19, top + 24, cx + 19, top + 44)
        shoulders.lineTo(cx - 19, top + 44)
        painter.drawPath(shoulders)

        if occupied:
            verdict = self.entry.get("verdict")
            border = QColor(VERDICT_STYLE[verdict][1]) if verdict in VERDICT_STYLE else QColor(90, 90, 90)
            # Selection is a light blue, not gold: gold reads as the amber
            # "marginal" verdict border and the two are hard to tell apart.
            painter.setPen(QPen(SELECTED_COLOR, 3) if self.selected else QPen(border, 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)

            painter.setPen(QColor(235, 230, 220))
            font = painter.font()
            font.setPointSize(7)
            painter.setFont(font)
            name = QFontMetrics(font).elidedText(self.entry["name"], Qt.ElideRight, self.width() - 6)
            painter.drawText(self.rect().adjusted(3, 0, -3, -4), Qt.AlignHCenter | Qt.AlignBottom, name)
        elif self.selected:
            painter.setPen(QPen(SELECTED_COLOR, 3))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)


class RosterWindow(QDialog):
    """A normal, focusable window (deliberately not the frameless always-on-top
    Tool style the overlay uses — that style couldn't reliably take keyboard
    focus on Windows)."""

    def __init__(self, guidance_by_name: dict, parent=None):
        super().__init__(parent)
        self._guidance_by_name = guidance_by_name
        self._entries = []
        self._selected_id = None
        self._syncing = False  # guards the table<->grid selection loop

        self.setWindowTitle("Company Roster")
        self.resize(900, 880)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        backdrop = BackgroundWidget(BACKGROUND_IMAGE)
        outer.addWidget(backdrop)

        layout = QVBoxLayout(backdrop)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.empty_label = QLabel(EMPTY_MESSAGE)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #b0bec5; font-style: italic; padding: 14px;")
        layout.addWidget(self.empty_label)

        # --- formation grid -------------------------------------------------
        formation_label = QLabel("Formation")
        formation_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(formation_label)

        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setSpacing(4)
        grid.setContentsMargins(0, 0, 0, 0)
        self.tiles = []
        for slot in range(roster.GRID_SLOTS):
            tile = SlotTile(slot)
            tile.clicked.connect(self._on_tile_clicked)
            grid.addWidget(tile, slot // roster.GRID_COLS, slot % roster.GRID_COLS)
            self.tiles.append(tile)
        layout.addWidget(grid_host, alignment=Qt.AlignHCenter)

        self.hint_label = QLabel(PLACE_HINT)
        self.hint_label.setStyleSheet("color: #90a4ae; font-size: 11px;")
        layout.addWidget(self.hint_label)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Background", "Building Toward", "Rating"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 180)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 260)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, stretch=1)

        self.detail = QTextBrowser()
        self.detail.setMinimumHeight(180)
        self.detail.setPlaceholderText("Select a brother to see his projected stats and target build.")
        layout.addWidget(self.detail)

        button_row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove from Roster")
        self.remove_btn.clicked.connect(self._on_remove)
        self.remove_btn.setEnabled(False)
        button_row.addWidget(self.remove_btn)
        button_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self):
        self._entries = roster.ensure_positions(roster.load_roster())
        self.empty_label.setVisible(not self._entries)

        by_slot = {e.get("position"): e for e in self._entries}
        for slot, tile in enumerate(self.tiles):
            entry = by_slot.get(slot)
            tile.set_entry(entry)
            tile.set_selected(
                self._selected_id is not None and entry is not None and entry["id"] == self._selected_id
            )

        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            self.table.setItem(row, 0, QTableWidgetItem(entry.get("name", "?")))
            self.table.setItem(row, 1, QTableWidgetItem(entry.get("background", "?")))
            self.table.setItem(row, 2, QTableWidgetItem(entry.get("archetype", "-")))

            rating_item = QTableWidgetItem(f"{entry.get('rating', 0):.1f}/10")
            rating_item.setTextAlignment(Qt.AlignCenter)
            verdict = entry.get("verdict")
            if verdict in VERDICT_STYLE:
                rating_item.setForeground(Qt.white)
                rating_item.setBackground(QColor(VERDICT_STYLE[verdict][1]))
            self.table.setItem(row, 3, rating_item)

        # Restore the table selection to whoever is selected on the grid.
        self._syncing = True
        self.table.clearSelection()
        if self._selected_id is not None:
            for row, entry in enumerate(self._entries):
                if entry["id"] == self._selected_id:
                    self.table.selectRow(row)
                    break
        self._syncing = False

        self._show_detail(self._selected_entry())

    def _selected_entry(self):
        if self._selected_id is None:
            return None
        return next((e for e in self._entries if e["id"] == self._selected_id), None)

    def _on_tile_clicked(self, slot: int):
        entry = next((e for e in self._entries if e.get("position") == slot), None)

        if self._selected_id is None:
            # Nothing held yet: clicking a brother picks him up.
            if entry is not None:
                self._select(entry["id"])
            return

        if entry is not None and entry["id"] == self._selected_id:
            self._select(None)  # click the held brother again to drop him
            return

        # A brother is held and a different slot was clicked -> move (or swap).
        roster.set_position(self._selected_id, slot)
        self.refresh()

    def _select(self, brother_id):
        self._selected_id = brother_id
        self.refresh()

    def _on_selection_changed(self):
        if self._syncing:
            return
        items = self.table.selectedItems()
        row = items[0].row() if items else None
        entry = self._entries[row] if row is not None and 0 <= row < len(self._entries) else None
        self._select(entry["id"] if entry else None)

    def _show_detail(self, entry):
        self.remove_btn.setEnabled(entry is not None)
        if entry is None:
            self.detail.clear()
            return

        projected = entry.get("projected", {})
        stars = entry.get("stars", {})
        rows = []
        for stat in STATS:
            star_count = stars.get(stat, 0)
            star_text = " " + "&#9733;" * star_count if star_count else ""
            rows.append(
                f'<tr><td style="padding-right:14px;">{STAT_LABELS[stat]}{star_text}</td>'
                f'<td align="right"><b>{projected.get(stat, "-")}</b></td></tr>'
            )

        guidance = self._guidance_by_name.get(entry.get("archetype")) or {}
        guidance_html = ""
        if guidance:
            priorities = " &rarr; ".join(
                _pretty_stat_tokens(t) for t in guidance.get("level_up_priority", [])
            )
            guidance_html = (
                f'<p style="margin:6px 0 2px 0;"><b>Level-up priority:</b> {priorities}</p>'
                f'<p style="margin:2px 0;"><b>Key perks:</b> {", ".join(guidance.get("key_perks", []))}</p>'
                f'<p style="margin:2px 0;"><b>Weapons / gear:</b> {", ".join(guidance.get("weapons", []))}</p>'
            )

        verdict_label = VERDICT_STYLE.get(entry.get("verdict"), ("", ""))[0]
        self.detail.setHtml(
            f'<h3 style="margin:2px 0;">{entry.get("name", "?")} '
            f'<span style="font-weight:normal; color:#b0bec5;">— {entry.get("background", "?")}</span></h3>'
            f'<p style="margin:2px 0; color:#b0bec5;">Building toward <b>{entry.get("archetype", "-")}</b>'
            f' &nbsp;·&nbsp; {verdict_label} {entry.get("rating", 0):.1f}/10'
            f' &nbsp;·&nbsp; added {entry.get("added", "?")}</p>'
            f'<p style="margin:6px 0 2px 0;"><b>Projected at level 11:</b></p>'
            f'<table>{"".join(rows)}</table>'
            f"{guidance_html}"
        )

    def _on_remove(self):
        entry = self._selected_entry()
        if entry is None:
            return
        confirm = QMessageBox.question(
            self,
            "Remove from Roster",
            f"Remove {entry.get('name', 'this brother')} from the roster?\n\nThis cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        roster.remove_brother(entry["id"])
        self._selected_id = None  # don't keep holding a brother who's now gone
        self.refresh()
