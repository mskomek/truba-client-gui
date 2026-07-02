from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from truba_gui.ui.widgets.remote_accordion import RemoteAccordion


class RemoteAccordionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.scratch = QLabel("scratch body")
        self.home = QLabel("home body")
        self.widget = RemoteAccordion(
            [
                ("scratch", "Scratch", self.scratch),
                ("home", "Home", self.home),
            ]
        )
        self.widget.show()
        QApplication.processEvents()

    def tearDown(self) -> None:
        self.widget.deleteLater()

    def test_exactly_one_body_is_visible(self) -> None:
        self.assertEqual(self.widget.active_key, "scratch")
        self.assertTrue(self.scratch.isVisible())
        self.assertFalse(self.home.isVisible())

        self.widget.set_active("home")
        QApplication.processEvents()
        self.assertEqual(self.widget.active_key, "home")
        self.assertFalse(self.scratch.isVisible())
        self.assertTrue(self.home.isVisible())

    def test_both_headers_remain_visible_and_keyboard_activates(self) -> None:
        scratch_button = self.widget._sections["scratch"][0]
        home_button = self.widget._sections["home"][0]
        self.assertTrue(scratch_button.isVisible())
        self.assertTrue(home_button.isVisible())

        home_button.setFocus()
        QTest.keyClick(home_button, Qt.Key.Key_Space)
        QApplication.processEvents()
        self.assertEqual(self.widget.active_key, "home")


if __name__ == "__main__":
    unittest.main()
