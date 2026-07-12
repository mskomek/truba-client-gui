from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from truba_gui.services.local_files import list_local_entries, safe_initial_local_directory
from truba_gui.ui.widgets.local_dir_panel import LocalDirPanel


class LocalDirPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path.cwd()
        self.panel = LocalDirPanel(str(self.root))

    def tearDown(self) -> None:
        QApplication.clipboard().clear()
        self.panel.deleteLater()

    def test_service_lists_folders_before_files_with_metadata(self) -> None:
        entries = list_local_entries(str(self.root))
        names = [entry.name for entry in entries]
        self.assertIn("src", names)
        self.assertIn("pyproject.toml", names)
        src = next(entry for entry in entries if entry.name == "src")
        pyproject = next(entry for entry in entries if entry.name == "pyproject.toml")
        self.assertTrue(src.is_dir)
        self.assertGreater(pyproject.size, 0)

    def test_panel_navigates_and_returns_to_parent(self) -> None:
        self.assertTrue(self.panel.set_dir(str(self.root / "src")))
        self.assertEqual(self.panel.current_dir, str(self.root / "src"))
        self.panel.go_parent()
        self.assertEqual(self.panel.current_dir, str(self.root))

    def test_directory_tabs_are_closable_except_last_tab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child"
            child.mkdir()

            self.assertTrue(self.panel.set_dir(str(root)))
            self.assertTrue(self.panel.open_directory_in_new_tab(str(child)))
            self.assertTrue(self.panel.tabs.tabsClosable())
            self.assertEqual(self.panel.tabs.count(), 2)

            self.panel._close_tab(self.panel.tabs.currentIndex())
            self.assertEqual(self.panel.tabs.count(), 1)
            self.assertEqual(Path(self.panel.current_dir), root)

            self.panel._close_tab(0)
            self.assertEqual(self.panel.tabs.count(), 1)

    def test_invalid_saved_path_falls_back_safely(self) -> None:
        fallback = safe_initial_local_directory(str(self.root / "__missing_wave030__"))
        self.assertTrue(os.path.isdir(fallback))

    @staticmethod
    def _names(panel: LocalDirPanel) -> list[str]:
        return [
            panel.tree.topLevelItem(index).text(0)
            for index in range(panel.tree.topLevelItemCount())
        ]

    def _click_header(self, column: int) -> None:
        self.panel.tree.header().sectionClicked.emit(column)
        QApplication.processEvents()

    def _press(self, key: Qt.Key, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
        event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers)
        QApplication.sendEvent(self.panel.tree, event)

    def _select_name(self, name: str) -> None:
        self.panel.tree.clearSelection()
        for index in range(self.panel.tree.topLevelItemCount()):
            item = self.panel.tree.topLevelItem(index)
            if item.text(0) == name:
                item.setSelected(True)
                return
        self.fail(f"local item not found: {name}")

    def _current_name(self) -> str:
        item = self.panel.tree.currentItem()
        self.assertIsNotNone(item)
        return item.text(0)

    def test_header_sorting_uses_name_size_type_and_modified_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "folder10").mkdir()
            (root / "Folder2").mkdir()
            files = {
                "file10.txt": b"x" * 900,
                "File2.txt": b"x" * 2048,
                "image2.iso": b"x" * 1024,
                "image10.iso": b"x" * 100,
                "archive10.zip": b"x" * 10,
                "archive2.7z": b"x" * 20,
            }
            for offset, (name, data) in enumerate(files.items(), start=1):
                path = root / name
                path.write_bytes(data)
                os.utime(path, (100 + offset, 100 + offset))

            self.assertTrue(self.panel.set_dir(str(root)))

            self._click_header(0)
            names = self._names(self.panel)
            self.assertEqual(names[:3], ["..", "Folder2", "folder10"])
            self.assertLess(names.index("archive2.7z"), names.index("archive10.zip"))
            self.assertLess(names.index("File2.txt"), names.index("file10.txt"))

            self._click_header(1)
            names = self._names(self.panel)
            self.assertLess(names.index("image10.iso"), names.index("file10.txt"))
            self.assertLess(names.index("file10.txt"), names.index("image2.iso"))
            self.assertLess(names.index("image2.iso"), names.index("File2.txt"))

            self._click_header(2)
            names = self._names(self.panel)
            self.assertLess(names.index("archive2.7z"), names.index("image2.iso"))
            self.assertLess(names.index("image2.iso"), names.index("File2.txt"))

            self._click_header(3)
            self.assertEqual(
                self.panel.tree.header().sortIndicatorSection(),
                3,
            )
            self.assertEqual(
                self.panel.tree.header().sortIndicatorOrder(),
                Qt.SortOrder.AscendingOrder,
            )
            self._click_header(3)
            self.assertEqual(
                self.panel.tree.header().sortIndicatorOrder(),
                Qt.SortOrder.DescendingOrder,
            )

    def test_keyboard_copy_cut_paste_between_local_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            (source_dir / "copy.txt").write_text("copy", encoding="utf-8")
            (source_dir / "move.txt").write_text("move", encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(source_dir)))
            self._select_name("copy.txt")
            self._press(Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

            self.assertTrue(self.panel.set_dir(str(target_dir)))
            self._press(Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual((target_dir / "copy.txt").read_text(encoding="utf-8"), "copy")
            self.assertTrue((source_dir / "copy.txt").exists())

            self.assertTrue(self.panel.set_dir(str(source_dir)))
            self._select_name("move.txt")
            self._press(Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
            self.assertTrue(self.panel.open_directory_in_new_tab(str(target_dir)))

            self._press(Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual((target_dir / "move.txt").read_text(encoding="utf-8"), "move")
            self.assertFalse((source_dir / "move.txt").exists())
            self.panel.tabs.setCurrentIndex(0)
            QApplication.processEvents()
            self.assertNotIn("move.txt", self._names(self.panel))

    def test_delete_and_ctrl_delete_remove_selected_local_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "delete.txt").write_text("delete", encoding="utf-8")
            (root / "ctrl-delete.txt").write_text("ctrl", encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(root)))
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                self._select_name("delete.txt")
                self._press(Qt.Key.Key_Delete)
                self.assertFalse((root / "delete.txt").exists())

                self._select_name("ctrl-delete.txt")
                self._press(Qt.Key.Key_Delete, Qt.KeyboardModifier.ControlModifier)
                self.assertFalse((root / "ctrl-delete.txt").exists())

    def test_local_page_home_end_shortcuts_move_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(20):
                (root / f"item-{index:02d}.txt").write_text(str(index), encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(root)))
            self._press(Qt.Key.Key_Home)
            self.assertEqual(self._current_name(), "..")

            self._press(Qt.Key.Key_End)
            self.assertEqual(self._current_name(), self._names(self.panel)[-1])

            self._press(Qt.Key.Key_PageUp)
            after_page_up = self._current_name()
            self.assertNotEqual(after_page_up, self._names(self.panel)[-1])

            self._press(Qt.Key.Key_PageDown)
            self.assertNotEqual(self._current_name(), after_page_up)

    def test_local_ctrl_v_emits_remote_clipboard_paste_request(self) -> None:
        from truba_gui.services.file_clipboard import get_file_clipboard

        emitted: list[tuple[list[str], str]] = []
        clipboard = get_file_clipboard()
        try:
            clipboard.set("copy", ["/remote/out.txt"])
            self.panel.remoteClipboardPasteRequested.connect(
                lambda paths, target: emitted.append((paths, target))
            )
            self._press(Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
            self.assertEqual(emitted, [(["/remote/out.txt"], self.panel.current_dir)])
        finally:
            clipboard.clear()

    def test_local_f5_refreshes_focused_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "first.txt").write_text("first", encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(root)))
            self.assertNotIn("second.txt", self._names(self.panel))

            (root / "second.txt").write_text("second", encoding="utf-8")
            self._press(Qt.Key.Key_F5)

            self.assertIn("second.txt", self._names(self.panel))

    def test_delete_removes_non_empty_local_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "recalculated"
            nested = target / "nested"
            nested.mkdir(parents=True)
            (nested / "result.txt").write_text("data", encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(root)))
            self._select_name("recalculated")
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                self.assertTrue(self.panel.delete_selected())

            self.assertFalse(target.exists())

    def test_delete_key_removes_selected_local_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "delete-key.txt"
            target.write_text("data", encoding="utf-8")

            self.assertTrue(self.panel.set_dir(str(root)))
            self._select_name("delete-key.txt")
            with patch(
                "truba_gui.ui.widgets.local_dir_panel.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                self._press(Qt.Key.Key_Delete)

            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
