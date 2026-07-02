import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath("src"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from truba_gui.ui.widgets.editor_widget import EditorWidget


class _FakeFiles:
    def __init__(self):
        self.data = {}

    def read_text(self, remote_path: str) -> str:
        return self.data[remote_path]

    def write_text(self, remote_path: str, text: str) -> None:
        self.data[remote_path] = text


class _FakeSlurm:
    def __init__(self, out: str):
        self.out = out
        self.calls = []

    def sbatch(self, script_path: str) -> str:
        self.calls.append(script_path)
        return self.out


class EditorFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.files = _FakeFiles()
        self.slurm = _FakeSlurm("Submitted batch job 12345")
        self.w = EditorWidget()
        self.w.set_session({"files": self.files, "slurm": self.slurm})

        self._orig_question = QMessageBox.question
        self._orig_info = QMessageBox.information
        self._orig_warn = QMessageBox.warning
        self._orig_critical = QMessageBox.critical
        QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
        self._history_patch = patch(
            "truba_gui.ui.widgets.editor_widget.append_event"
        )
        self._history_patch.start()

    def tearDown(self):
        QMessageBox.question = self._orig_question
        QMessageBox.information = self._orig_info
        QMessageBox.warning = self._orig_warn
        QMessageBox.critical = self._orig_critical
        self._history_patch.stop()
        self.w.deleteLater()

    def test_save_submit_emits_job_signal(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        got = []
        self.w.script_submitted.connect(lambda jid, path: got.append((jid, path)))
        self.w.path_in.setText("/arf/scratch/user/a.slurm")
        self.w.text.setPlainText("#!/bin/bash\n#SBATCH -p orfoz\necho ok\n")

        self.w.save_path(force_submit=True)

        self.assertEqual(self.files.data["/arf/scratch/user/a.slurm"].strip().splitlines()[0], "#!/bin/bash")
        self.assertEqual(self.slurm.calls, ["/arf/scratch/user/a.slurm"])
        self.assertEqual(got, [("12345", "/arf/scratch/user/a.slurm")])

    def test_save_non_slurm_does_not_submit(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        self.w.path_in.setText("/arf/scratch/user/readme.txt")
        self.w.text.setPlainText("hello")

        self.w.save_path()

        self.assertEqual(self.files.data["/arf/scratch/user/readme.txt"], "hello")
        self.assertEqual(self.slurm.calls, [])

    def test_validation_can_block_save(self):
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.No)
        self.w.path_in.setText("/arf/scratch/user/bad.slurm")
        self.w.text.setPlainText("echo no directives")

        self.w.save_path(force_submit=True)

        self.assertNotIn("/arf/scratch/user/bad.slurm", self.files.data)
        self.assertEqual(self.slurm.calls, [])

    def test_opening_multiple_files_creates_tabs_and_reuses_same_path(self):
        self.w.open_file("/arf/scratch/user/a.txt", "alpha")
        self.w.open_file("/arf/scratch/user/b.txt", "beta")

        self.assertEqual(self.w.document_tabs.count(), 2)
        self.assertEqual(self.w.path_in.text(), "/arf/scratch/user/b.txt")
        self.assertEqual(self.w.text.toPlainText(), "beta")

        self.w.open_file("/arf/scratch/user/a.txt", "replacement")
        self.assertEqual(self.w.document_tabs.count(), 2)
        self.assertEqual(self.w.path_in.text(), "/arf/scratch/user/a.txt")
        self.assertEqual(self.w.text.toPlainText(), "alpha")

    def test_save_targets_active_document(self):
        self.w.open_file("/arf/scratch/user/a.txt", "alpha")
        self.w.open_file("/arf/scratch/user/b.txt", "beta")
        self.w.text.setPlainText("beta changed")

        self.w.save_path()

        self.assertEqual(
            self.files.data["/arf/scratch/user/b.txt"],
            "beta changed",
        )
        self.assertNotIn("/arf/scratch/user/a.txt", self.files.data)

    def test_document_tabs_are_closable(self):
        self.w.open_file("/arf/scratch/user/a.txt", "alpha")
        self.w.open_file("/arf/scratch/user/b.txt", "beta")
        self.assertTrue(self.w.document_tabs.tabsClosable())

        self.w._close_document_tab(1)

        self.assertEqual(self.w.document_tabs.count(), 1)
        self.assertEqual(self.w.path_in.text(), "/arf/scratch/user/a.txt")

    def test_ctrl_s_saves_active_document(self):
        self.w.open_file("/arf/scratch/user/save.txt", "before")
        self.w.text.setPlainText("after")
        self.w.show()
        self.w.text.setFocus()

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_S,
            Qt.KeyboardModifier.ControlModifier,
        )
        self._app.processEvents()

        self.assertEqual(
            self.files.data["/arf/scratch/user/save.txt"],
            "after",
        )

    def test_undo_redo_and_select_all_shortcuts_target_active_editor(self):
        self.w.open_file("/arf/scratch/user/keys.txt", "")
        self.w.show()
        self.w.text.setFocus()
        QTest.keyClicks(self.w.text, "abc")

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_Z,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(self.w.text.toPlainText(), "")
        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_Y,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(self.w.text.toPlainText(), "abc")
        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertTrue(self.w.text.textCursor().hasSelection())

    def test_tab_switch_close_and_find_shortcuts(self):
        self.w.open_file("/arf/scratch/user/a.txt", "alpha needle")
        self.w.open_file("/arf/scratch/user/b.txt", "beta")
        self.w.show()
        self.w.text.setFocus()

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_Tab,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(self.w.path_in.text(), "/arf/scratch/user/a.txt")

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_F,
            Qt.KeyboardModifier.ControlModifier,
        )
        self._app.processEvents()
        self.assertTrue(self.w.find_bar.isVisible())
        self.assertEqual(self._app.focusWidget(), self.w.find_in)
        self.w.find_in.setText("needle")
        QTest.keyClick(self.w.find_in, Qt.Key.Key_Return)
        self.assertEqual(self.w.text.textCursor().selectedText(), "needle")

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_W,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.assertEqual(self.w.document_tabs.count(), 1)

    def test_find_replace_bar_replaces_current_and_all_matches(self):
        self.w.open_file("/arf/scratch/user/find.txt", "alpha beta alpha")
        self.w.show()
        self.w.text.setFocus()

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_F,
            Qt.KeyboardModifier.ControlModifier,
        )
        self.w.find_in.setText("alpha")
        self.w.replace_in.setText("gamma")
        self.w.find_next()
        self.assertEqual(self.w.text.textCursor().selectedText(), "alpha")

        self.assertTrue(self.w.replace_current())
        self.assertEqual(self.w.text.toPlainText(), "gamma beta alpha")

        self.w.find_in.setText("alpha")
        self.w.replace_in.setText("delta")
        self.assertEqual(self.w.replace_all(), 1)
        self.assertEqual(self.w.text.toPlainText(), "gamma beta delta")

    def test_ctrl_o_focuses_remote_path_and_enter_opens_it(self):
        self.files.data["/arf/scratch/user/open.txt"] = "opened"
        self.w.show()
        self.w.text.setFocus()

        QTest.keyClick(
            self.w.text,
            Qt.Key.Key_O,
            Qt.KeyboardModifier.ControlModifier,
        )
        self._app.processEvents()
        self.assertTrue(self.w.path_in.hasFocus())
        self.w.path_in.setText("/arf/scratch/user/open.txt")
        QTest.keyClick(self.w.path_in, Qt.Key.Key_Return)

        self.assertEqual(self.w.path_in.text(), "/arf/scratch/user/open.txt")
        self.assertEqual(self.w.text.toPlainText(), "opened")

    def test_editor_page_navigation_and_end_work_in_active_tab(self):
        self.w.open_file(
            "/arf/scratch/user/long.txt",
            "\n".join(f"line {index}" for index in range(300)),
        )
        self.w.resize(500, 240)
        self.w.show()
        self.w.text.setFocus()
        self._app.processEvents()
        scrollbar = self.w.text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        QTest.keyClick(self.w.text, Qt.Key.Key_PageUp)
        self._app.processEvents()
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        QTest.keyClick(self.w.text, Qt.Key.Key_End)
        self._app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())


if __name__ == "__main__":
    unittest.main()
