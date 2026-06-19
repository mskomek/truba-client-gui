from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


class _Files:
    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.writes: list[tuple[str, str]] = []

    def exists(self, path: str) -> bool:
        return path in self.paths

    def mkdir(self, path: str) -> None:
        self.paths.add(path)

    def write_text(self, path: str, text: str) -> None:
        self.paths.add(path)
        self.writes.append((path, text))

    def listdir_entries(self, _path: str):
        return []


class RemoteDirPanelCreateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.files = _Files()
        self.panel = RemoteDirPanel()
        self.panel.set_session({"connected": True, "files": self.files})
        self.panel.current_dir = "/arf/scratch/user"

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_create_folder_in_requested_parent(self) -> None:
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.QInputDialog.getText",
            return_value=("results", True),
        ):
            self.assertTrue(self.panel.create_new_folder("/arf/scratch/user/job"))

        self.assertIn("/arf/scratch/user/job/results", self.files.paths)

    def test_create_empty_file_in_current_directory(self) -> None:
        with patch(
            "truba_gui.ui.widgets.remote_dir_panel.QInputDialog.getText",
            return_value=("notes.txt", True),
        ):
            self.assertTrue(self.panel.create_new_file())

        self.assertEqual(
            self.files.writes,
            [("/arf/scratch/user/notes.txt", "")],
        )

    def test_rejects_path_separators(self) -> None:
        with (
            patch(
                "truba_gui.ui.widgets.remote_dir_panel.QInputDialog.getText",
                return_value=("../bad", True),
            ),
            patch("truba_gui.ui.widgets.remote_dir_panel.QMessageBox.warning") as warning,
        ):
            self.assertFalse(self.panel.create_new_file())

        warning.assert_called_once()
        self.assertEqual(self.files.writes, [])


if __name__ == "__main__":
    unittest.main()
