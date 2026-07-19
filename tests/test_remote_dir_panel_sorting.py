from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from truba_gui.services.files_base import RemoteEntry
from truba_gui.ui.widgets.remote_dir_panel import RemoteDirPanel


class _Files:
    def __init__(self, entries: list[RemoteEntry]) -> None:
        self.entries = entries

    def listdir_entries(self, _path: str) -> list[RemoteEntry]:
        return list(self.entries)


class RemoteDirPanelSortingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.entries = [
            RemoteEntry("folder10", "/work/folder10", True, size=9000, mtime=400),
            RemoteEntry("Folder2", "/work/Folder2", True, size=1, mtime=100),
            RemoteEntry("file10.txt", "/work/file10.txt", False, size=900, mtime=300),
            RemoteEntry("File2.txt", "/work/File2.txt", False, size=2048, mtime=200),
            RemoteEntry("image2.iso", "/work/image2.iso", False, size=1024 * 1024, mtime=500),
            RemoteEntry("image10.iso", "/work/image10.iso", False, size=100, mtime=600),
            RemoteEntry("archive10.zip", "/work/archive10.zip", False, size=10, mtime=800),
            RemoteEntry("archive2.7z", "/work/archive2.7z", False, size=20, mtime=700),
            RemoteEntry("typed10.x10", "/work/typed10.x10", False, size=30, mtime=1000),
            RemoteEntry("Typed2.X2", "/work/Typed2.X2", False, size=40, mtime=1100),
            RemoteEntry("plain", "/work/plain", False, size=2, mtime=900),
        ]
        self.files = _Files(self.entries)
        self.panel = RemoteDirPanel()
        self.panel.set_session({"connected": True, "files": self.files})
        self.panel.set_dir("/work")

    def tearDown(self) -> None:
        self.panel.deleteLater()

    @staticmethod
    def _names(view) -> list[str]:
        return [view.topLevelItem(i).text(0) for i in range(view.topLevelItemCount())]

    def _click(self, view, column: int) -> None:
        view.header().sectionClicked.emit(column)
        QApplication.processEvents()

    def _assert_fixed_groups(self, names: list[str]) -> None:
        self.assertEqual(names[0], "..")
        self.assertEqual(set(names[1:3]), {"folder10", "Folder2"})
        self.assertFalse(any(name.startswith("folder") for name in names[3:]))

    def test_name_sorts_naturally_both_directions_with_fixed_groups(self) -> None:
        view = self.panel.views["all"]

        self._click(view, 0)
        self.assertEqual(
            self._names(view)[:7],
            ["..", "Folder2", "folder10", "archive2.7z", "archive10.zip", "File2.txt", "file10.txt"],
        )
        self._click(view, 0)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("file10.txt"), names.index("File2.txt"))
        self.assertLess(names.index("archive10.zip"), names.index("archive2.7z"))

    def test_size_uses_raw_bytes_in_both_directions(self) -> None:
        view = self.panel.views["all"]

        self._click(view, 1)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("image10.iso"), names.index("file10.txt"))
        self.assertLess(names.index("file10.txt"), names.index("File2.txt"))
        self.assertLess(names.index("File2.txt"), names.index("image2.iso"))

        self._click(view, 1)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("image2.iso"), names.index("File2.txt"))
        self.assertLess(names.index("File2.txt"), names.index("file10.txt"))
        self.assertLess(names.index("file10.txt"), names.index("image10.iso"))

    def test_modified_uses_raw_timestamp_in_both_directions(self) -> None:
        view = self.panel.views["all"]

        self._click(view, 3)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("File2.txt"), names.index("file10.txt"))
        self.assertLess(names.index("archive2.7z"), names.index("archive10.zip"))

        self._click(view, 3)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("archive10.zip"), names.index("archive2.7z"))
        self.assertLess(names.index("file10.txt"), names.index("File2.txt"))

    def test_type_sorts_case_insensitively_naturally_both_directions(self) -> None:
        view = self.panel.views["all"]

        self._click(view, 2)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("image2.iso"), names.index("archive10.zip"))
        self.assertLess(names.index("Typed2.X2"), names.index("typed10.x10"))

        self._click(view, 2)
        names = self._names(view)
        self._assert_fixed_groups(names)
        self.assertLess(names.index("archive10.zip"), names.index("image2.iso"))
        self.assertLess(names.index("typed10.x10"), names.index("Typed2.X2"))

    def test_header_indicator_and_direction_toggle_for_every_column(self) -> None:
        view = self.panel.views["all"]
        for column in range(4):
            self._click(view, column)
            self.assertTrue(view.header().isSortIndicatorShown())
            self.assertEqual(view.header().sortIndicatorSection(), column)
            self.assertEqual(view.header().sortIndicatorOrder(), Qt.SortOrder.AscendingOrder)
            self._click(view, column)
            self.assertEqual(view.header().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)

    def test_refresh_preserves_sort_and_all_categories_share_behavior(self) -> None:
        all_view = self.panel.views["all"]
        self._click(all_view, 1)
        self._click(all_view, 1)
        before = self._names(all_view)

        self.files.entries = list(reversed(self.files.entries))
        self.panel.refresh()
        self.assertEqual(self._names(all_view), before)
        self.assertEqual(all_view.header().sortIndicatorSection(), 1)
        self.assertEqual(all_view.header().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder)

        for key, view in self.panel.views.items():
            self._click(view, 0)
            self.assertTrue(view.header().isSortIndicatorShown(), key)
            self.assertEqual(view.header().sortIndicatorSection(), 0, key)
            self._click(view, 0)
            self.assertEqual(view.header().sortIndicatorOrder(), Qt.SortOrder.DescendingOrder, key)
            names = self._names(view)
            if key in ("all", "folders"):
                self.assertEqual(names[0], "..", key)


if __name__ == "__main__":
    unittest.main()
