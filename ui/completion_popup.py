"""Floating completion popup used by the chat composer for ``/``, ``@`` and ``;``.

Each row has an icon, a title, a muted description and a badge drawn on the
right. The row *text* stays ``"title  —  description"`` so accessibility tools
and tests read something meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
)

from ui import theme

BADGE_ROLE = Qt.ItemDataRole.UserRole + 1
COMPLETION_ROLE = Qt.ItemDataRole.UserRole


@dataclass
class CompletionItem:
    title: str                 # shown text, e.g. "/clear" or "@browser-helper"
    completion: str            # text inserted into the composer
    description: str = ""
    badge: str = ""            # e.g. "cmd", "skill", "MCP", "file"
    icon: QIcon | None = None
    enabled: bool = True
    extra: dict = field(default_factory=dict)


def fuzzy_score(query: str, text: str) -> int | None:
    """Return a rank (lower is better) or None when ``query`` does not match.

    Case-insensitive. Prefix < substring < in-order subsequence.
    """
    q, t = query.casefold(), text.casefold()
    if not q:
        return 0
    if t.startswith(q):
        return 0
    idx = t.find(q)
    if idx >= 0:
        return 10 + idx
    pos = -1
    gaps = 0
    for ch in q:
        nxt = t.find(ch, pos + 1)
        if nxt < 0:
            return None
        gaps += nxt - pos - 1 if pos >= 0 else 0
        pos = nxt
    return 100 + gaps


def filter_items(items: list[CompletionItem], query: str, limit: int = 10,
                 key=lambda i: i.title) -> list[CompletionItem]:
    scored: list[tuple[int, int, CompletionItem]] = []
    for order, item in enumerate(items):
        score = fuzzy_score(query, key(item).lstrip("/@;"))
        if score is not None:
            scored.append((score, order, item))
    scored.sort(key=lambda s: (s[0], s[1]))
    return [item for _s, _o, item in scored[:limit]]


class _Delegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        t = theme.tokens()
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = option.rect
        if selected:
            painter.fillRect(rect, QColor(t["primary"]))
        fg = QColor(t["on_primary"] if selected else t["text"])
        muted = QColor(t["on_primary"] if selected else t["muted"])
        if not (index.flags() & Qt.ItemFlag.ItemIsEnabled):
            fg = muted = QColor(t["muted"])

        x = rect.left() + 8
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            icon.paint(painter, QRect(x, rect.top() + 5, 16, 16))
            x += 22

        badge = index.data(BADGE_ROLE) or ""
        right = rect.right() - 8
        fm = QFontMetrics(painter.font())
        if badge:
            bw = fm.horizontalAdvance(badge) + 12
            brect = QRect(right - bw, rect.top() + 4, bw, rect.height() - 8)
            painter.setPen(Qt.PenStyle.NoPen)
            border = QColor(t["on_primary"] if selected else t["border"])
            painter.setBrush(border if not selected else QColor(0, 0, 0, 40))
            painter.drawRoundedRect(brect, 8, 8)
            painter.setPen(muted)
            painter.drawText(brect, Qt.AlignmentFlag.AlignCenter, badge)
            right = brect.left() - 8

        title = index.data(Qt.ItemDataRole.UserRole + 2) or ""
        desc = index.data(Qt.ItemDataRole.UserRole + 3) or ""
        painter.setPen(fg)
        title_w = fm.horizontalAdvance(title)
        painter.drawText(QRect(x, rect.top(), max(0, right - x), rect.height()),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        if desc:
            dx = x + title_w + 12
            if dx < right:
                painter.setPen(muted)
                painter.drawText(
                    QRect(dx, rect.top(), right - dx, rect.height()),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    fm.elidedText(desc, Qt.TextElideMode.ElideRight, right - dx),
                )
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 26)


class CompletionPopup(QListWidget):
    """A non-focus-stealing list that lives as a child of the main window."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("completionPopup")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setItemDelegate(_Delegate(self))
        self.setAccessibleName("Completion suggestions")
        self.hide()

    def set_items(self, items: list[CompletionItem]) -> None:
        self.clear()
        for it in items:
            text = f"{it.title}  —  {it.description}" if it.description else it.title
            row = QListWidgetItem(text)
            row.setData(COMPLETION_ROLE, it.completion if it.enabled else "")
            row.setData(BADGE_ROLE, it.badge)
            row.setData(Qt.ItemDataRole.UserRole + 2, it.title)
            row.setData(Qt.ItemDataRole.UserRole + 3, it.description)
            if it.icon is not None:
                row.setIcon(it.icon)
            if not it.enabled:
                row.setFlags(Qt.ItemFlag.NoItemFlags)
            self.addItem(row)
        for i in range(self.count()):
            if self.item(i).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.setCurrentRow(i)
                break

    def move_selection(self, step: int) -> None:
        count = self.count()
        if not count:
            return
        row = self.currentRow()
        for _ in range(count):
            row = (row + step) % count if row >= 0 else 0
            if self.item(row).flags() & Qt.ItemFlag.ItemIsEnabled:
                self.setCurrentRow(row)
                return

    def current_completion(self) -> str | None:
        item = self.currentItem()
        if item is None:
            return None
        return item.data(COMPLETION_ROLE) or None
