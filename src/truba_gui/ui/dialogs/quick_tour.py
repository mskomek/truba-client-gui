from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from truba_gui.core.i18n import t
from truba_gui.config.storage import set_ui_pref_bool


@dataclass
class TourStep:
    title: str
    body: str
    target_getter: Callable[[], Optional[QWidget]]
    tab_index: Optional[int] = None


class QuickTourOverlay(QWidget):
    """Simple spotlight-style onboarding overlay."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.steps: list[TourStep] = self._build_steps()
        self.idx = 0
        self._target: Optional[QWidget] = None
        self._target_rect = QRectF()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.panel = QFrame(self)
        self.panel.setStyleSheet(
            "QFrame { background: #ffffff; border: 1px solid #cfcfcf; border-radius: 10px; }"
            "QLabel#tourTitle { font-weight: 700; font-size: 14px; }"
        )
        self.lbl_title = QLabel(self.panel)
        self.lbl_title.setObjectName("tourTitle")
        self.lbl_body = QLabel(self.panel)
        self.lbl_body.setWordWrap(True)
        self.lbl_step = QLabel(self.panel)
        self.cb_no_show = QCheckBox(t("help.dont_show_again"), self.panel)

        self.btn_prev = QPushButton(t("tour.prev"), self.panel)
        self.btn_next = QPushButton(t("tour.next"), self.panel)
        self.btn_skip = QPushButton(t("tour.skip"), self.panel)
        self.btn_prev.clicked.connect(self.prev_step)
        self.btn_next.clicked.connect(self.next_step)
        self.btn_skip.clicked.connect(self.close)

        row = QHBoxLayout()
        row.addWidget(self.lbl_step)
        row.addWidget(self.cb_no_show)
        row.addStretch(1)
        row.addWidget(self.btn_prev)
        row.addWidget(self.btn_next)
        row.addWidget(self.btn_skip)

        lay = QVBoxLayout(self.panel)
        lay.addWidget(self.lbl_title)
        lay.addWidget(self.lbl_body)
        lay.addLayout(row)

        self.main_window.installEventFilter(self)
        self._refresh()

    def _build_steps(self) -> list[TourStep]:
        m = self.main_window
        return [
            TourStep(
                title=t("tour.s1_title"),
                body=t("tour.s1_body"),
                target_getter=lambda: getattr(m.login, "host", None),
                tab_index=m.tabs.indexOf(m.login),
            ),
            TourStep(
                title=t("tour.s2_title"),
                body=t("tour.s2_body"),
                target_getter=lambda: getattr(m.login, "cb_x11", None),
                tab_index=m.tabs.indexOf(m.login),
            ),
            TourStep(
                title=t("tour.s3_title"),
                body=t("tour.s3_body"),
                target_getter=lambda: getattr(m.login, "cmd_in", None),
                tab_index=m.tabs.indexOf(m.login),
            ),
            TourStep(
                title=t("tour.s4_title"),
                body=t("tour.s4_body"),
                target_getter=lambda: getattr(m.jobs_outputs, "btn_refresh", None),
                tab_index=m.tabs.indexOf(m.jobs_outputs),
            ),
            TourStep(
                title=t("tour.s5_title"),
                body=t("tour.s5_body"),
                target_getter=lambda: getattr(m.directories, "panel_scratch", None),
                tab_index=m.tabs.indexOf(m.directories),
            ),
            TourStep(
                title=t("tour.s6_title"),
                body=t("tour.s6_body"),
                target_getter=lambda: getattr(m.logs, "btn_diag", None),
                tab_index=m.tabs.indexOf(m.logs),
            ),
        ]

    def eventFilter(self, obj, event):
        if obj is self.main_window:
            if event.type() in (
                QEvent.Type.Resize,
                QEvent.Type.Move,
            ):
                self.setGeometry(self.main_window.rect())
                self._refresh_target()
                self._layout_panel()
                self.update()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        self.setGeometry(self.main_window.rect())
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self._refresh()

    def _refresh_target(self):
        self._target = None
        self._target_rect = QRectF()
        step = self.steps[self.idx]
        if step.tab_index is not None and step.tab_index >= 0:
            self.main_window.tabs.setCurrentIndex(step.tab_index)
            # Let Qt settle layouts after tab switch before mapping coordinates.
            QApplication.processEvents()
        target = step.target_getter()
        if target is None or not target.isVisible():
            return
        top_left = target.mapToGlobal(QPoint(0, 0))
        bottom_right = target.mapToGlobal(QPoint(target.width(), target.height()))
        p = self.mapFromGlobal(top_left)
        p2 = self.mapFromGlobal(bottom_right)
        w = max(16, p2.x() - p.x())
        h = max(16, p2.y() - p.y())
        self._target = target
        self._target_rect = QRectF(
            p.x() - 6,
            p.y() - 6,
            w + 12,
            h + 12,
        )

    def _layout_panel(self):
        w = min(460, max(320, int(self.width() * 0.42)))
        h = 170
        margin = 16
        x = self.width() - w - margin
        y = self.height() - h - margin
        if not self._target_rect.isNull():
            if self._target_rect.top() > h + 32:
                y = max(margin, int(self._target_rect.top()) - h - 12)
            elif self._target_rect.right() < self.width() - w - 24:
                x = min(self.width() - w - margin, int(self._target_rect.right()) + 12)
                y = max(margin, min(y, int(self._target_rect.top())))
        self.panel.setGeometry(x, y, w, h)

    def _refresh(self):
        step = self.steps[self.idx]
        self.lbl_title.setText(step.title)
        self.lbl_body.setText(step.body)
        self.lbl_step.setText(f"{self.idx + 1}/{len(self.steps)}")
        self.btn_prev.setEnabled(self.idx > 0)
        self.btn_next.setText(t("tour.finish") if self.idx == len(self.steps) - 1 else t("tour.next"))
        self._refresh_target()
        self._layout_panel()
        self.update()

    def next_step(self):
        if self.idx >= len(self.steps) - 1:
            self.close()
            return
        self.idx += 1
        self._refresh()

    def prev_step(self):
        if self.idx <= 0:
            return
        self.idx -= 1
        self._refresh()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.setFillRule(Qt.FillRule.OddEvenFill)
        path.addRect(self.rect())
        if not self._target_rect.isNull():
            path.addRoundedRect(self._target_rect, 10, 10)
        p.fillPath(path, QColor(0, 0, 0, 170))
        if not self._target_rect.isNull():
            p.setPen(QColor(255, 255, 255, 220))
            p.drawRoundedRect(self._target_rect, 10, 10)
        super().paintEvent(event)

    def closeEvent(self, event):
        try:
            if self.cb_no_show.isChecked():
                set_ui_pref_bool("show_tour", False)
        except Exception:
            pass
        super().closeEvent(event)
