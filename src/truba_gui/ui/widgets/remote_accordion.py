from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QToolButton, QVBoxLayout, QWidget


class RemoteAccordion(QWidget):
    activeChanged = Signal(str)

    def __init__(self, sections: list[tuple[str, str, QWidget]], parent=None) -> None:
        super().__init__(parent)
        self._sections: dict[str, tuple[QToolButton, QWidget]] = {}
        self._active_key = sections[0][0] if sections else ""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        for key, title, body in sections:
            button = QToolButton(self)
            button.setText(title)
            button.setCheckable(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setArrowType(Qt.ArrowType.RightArrow)
            button.setSizePolicy(button.sizePolicy().horizontalPolicy(), button.sizePolicy().verticalPolicy())
            button.setAccessibleName(title)
            button.clicked.connect(lambda _checked=False, selected=key: self.set_active(selected))
            layout.addWidget(button)
            layout.addWidget(body, 1)
            self._sections[key] = (button, body)
        self.set_active(self._active_key, emit=False)

    @property
    def active_key(self) -> str:
        return self._active_key

    def body(self, key: str) -> QWidget | None:
        section = self._sections.get(key)
        return section[1] if section else None

    def set_title(self, key: str, title: str) -> None:
        section = self._sections.get(key)
        if not section:
            return
        button, _body = section
        button.setText(title)
        button.setAccessibleName(title)

    def set_active(self, key: str, *, emit: bool = True) -> None:
        if key not in self._sections:
            return
        self._active_key = key
        for section_key, (button, body) in self._sections.items():
            expanded = section_key == key
            button.setChecked(expanded)
            button.setArrowType(
                Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
            )
            body.setVisible(expanded)
        if emit:
            self.activeChanged.emit(key)
