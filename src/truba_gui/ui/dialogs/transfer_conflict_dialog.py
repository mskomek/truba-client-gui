from __future__ import annotations

import datetime
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from truba_gui.core.i18n import t


def _tr(key: str, fallback: str) -> str:
    value = t(key)
    return fallback if value == f"[{key}]" else value


_ACTION_FALLBACKS = {
    "overwrite": "Overwrite",
    "overwrite_if_newer": "Overwrite if source newer",
    "overwrite_if_size_differs": "Overwrite if different size",
    "overwrite_if_size_differs_or_newer": "Overwrite if different size or source newer",
    "resume": "Resume",
    "rename": "Rename",
    "skip": "Skip",
}


@dataclass(frozen=True)
class TransferConflictInfo:
    path: str
    size: int | None = None
    mtime: int | None = None


@dataclass(frozen=True)
class TransferConflictDecision:
    action: str
    always_use: bool = False
    apply_current_queue_only: bool = False
    apply_downloads_only: bool = False


class TransferConflictDialog(QDialog):
    ACTIONS = (
        "overwrite",
        "overwrite_if_newer",
        "overwrite_if_size_differs",
        "overwrite_if_size_differs_or_newer",
        "resume",
        "rename",
        "skip",
    )

    def __init__(
        self,
        parent=None,
        *,
        source: TransferConflictInfo,
        target: TransferConflictInfo,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            _tr("transfer.conflict_title", "Target file already exists")
        )
        self._source = source
        self._target = target
        self._accepted = False

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.addWidget(
            QLabel(
                _tr(
                    "transfer.conflict_intro",
                    "The target file already exists.\nPlease choose an action.",
                )
            )
        )

        body = QHBoxLayout()
        file_col = QVBoxLayout()
        file_col.setSpacing(6)
        file_col.addWidget(self._file_block(_tr("transfer.source_file", "Source file:"), source))
        file_col.addSpacing(8)
        file_col.addWidget(self._file_block(_tr("transfer.target_file", "Target file:"), target))
        file_col.addStretch(1)
        body.addLayout(file_col, 1)

        right_col = QVBoxLayout()
        action_box = QGroupBox(_tr("transfer.conflict_action", "Action:"))
        action_layout = QVBoxLayout(action_box)
        action_layout.setSpacing(4)
        self.action_buttons: dict[str, QRadioButton] = {}
        for action in self.ACTIONS:
            button = QRadioButton(
                _tr(f"transfer.conflict_{action}", _ACTION_FALLBACKS[action])
            )
            self.action_buttons[action] = button
            action_layout.addWidget(button)
        self.action_buttons["overwrite"].setChecked(True)
        right_col.addWidget(action_box)

        options = QVBoxLayout()
        options.setSpacing(4)
        options.setContentsMargins(0, 4, 0, 0)
        self.cb_always = QCheckBox(
            _tr("transfer.conflict_always_use", "Always use this action")
        )
        self.cb_queue_only = QCheckBox(
            _tr("transfer.conflict_current_queue_only", "Apply to current queue only")
        )
        self.cb_downloads_only = QCheckBox(
            _tr("transfer.conflict_downloads_only", "Apply only to downloads")
        )
        options.addWidget(self.cb_always)
        options.addWidget(self.cb_queue_only)
        options.addWidget(self.cb_downloads_only)
        right_col.addLayout(options)
        right_col.addStretch(1)
        body.addLayout(right_col)
        root.addLayout(body)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _file_block(self, title: str, info: TransferConflictInfo) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(QLabel(title))
        path_label = QLabel(info.path)
        path_label.setTextInteractionFlags(
            path_label.textInteractionFlags()
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(path_label)

        detail_row = QHBoxLayout()
        icon_label = QLabel()
        icon_label.setPixmap(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon).pixmap(24, 24)
        )
        detail_row.addWidget(icon_label)
        detail_row.addWidget(QLabel(self._format_info(info)), 1)
        layout.addLayout(detail_row)
        return container

    @staticmethod
    def _format_time(ts: int | None) -> str:
        if not ts:
            return "-"
        try:
            dt = datetime.datetime.fromtimestamp(int(ts))
            hour = dt.hour % 12 or 12
            suffix = "AM" if dt.hour < 12 else "PM"
            return (
                f"{dt.month}/{dt.day}/{dt.year} "
                f"{hour}:{dt.minute:02d}:{dt.second:02d} {suffix}"
            )
        except Exception:
            return "-"

    @staticmethod
    def _format_size(size: int | None) -> str:
        if size is None:
            return "-"
        try:
            return f"{int(size):,} B"
        except Exception:
            return "-"

    @classmethod
    def _format_info(cls, info: TransferConflictInfo) -> str:
        return _tr("transfer.conflict_file_info", "{size}\n{mtime}").format(
            size=cls._format_size(info.size),
            mtime=cls._format_time(info.mtime),
        )

    def selected_action(self) -> str:
        for action, button in self.action_buttons.items():
            if button.isChecked():
                return action
        return "overwrite"

    def decision(self) -> TransferConflictDecision:
        return TransferConflictDecision(
            action=self.selected_action(),
            always_use=bool(self.cb_always.isChecked()),
            apply_current_queue_only=bool(self.cb_queue_only.isChecked()),
            apply_downloads_only=bool(self.cb_downloads_only.isChecked()),
        )

    def accept(self) -> None:  # type: ignore[override]
        self._accepted = True
        super().accept()

    @classmethod
    def get_decision(
        cls,
        parent,
        *,
        source: TransferConflictInfo,
        target: TransferConflictInfo,
    ) -> TransferConflictDecision:
        dialog = cls(parent, source=source, target=target)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return TransferConflictDecision(action="cancel")
        return dialog.decision()
