from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTextEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from truba_gui.ui.widgets.jobs_outputs_widget import (
    JobsOutputsWidget,
    _NavigableTextEdit,
)


class JobsOutputsScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.editor = _NavigableTextEdit()
        self.editor.resize(320, 120)
        self.editor.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.editor.close()
        self.editor.deleteLater()

    @staticmethod
    def _lines(count: int) -> str:
        return "\n".join(f"line {index}" for index in range(count))

    def test_live_follow_scrolls_to_latest_line(self) -> None:
        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(200),
            follow_latest=True,
        )

        self.assertEqual(
            self.editor.textCursor().position(),
            len(self.editor.toPlainText()),
        )
        self.app.processEvents()

        scrollbar = self.editor.verticalScrollBar()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_refresh_without_follow_preserves_scroll_position(self) -> None:
        self.editor.setPlainText(self._lines(200))
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(25)

        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(220),
            follow_latest=False,
        )
        self.app.processEvents()

        self.assertEqual(scrollbar.value(), 25)
        self.assertLess(scrollbar.value(), scrollbar.maximum())

    def test_bottom_state_controls_follow_per_refresh(self) -> None:
        self.editor.setPlainText(self._lines(200))
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        self.assertTrue(JobsOutputsWidget._is_scrolled_to_bottom(self.editor))

        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(220),
            follow_latest=JobsOutputsWidget._is_scrolled_to_bottom(self.editor),
        )
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

        scrollbar.setValue(max(0, scrollbar.maximum() - 20))
        self.assertFalse(JobsOutputsWidget._is_scrolled_to_bottom(self.editor))
        previous = scrollbar.value()
        JobsOutputsWidget._set_live_text(
            self.editor,
            self._lines(230),
            follow_latest=JobsOutputsWidget._is_scrolled_to_bottom(self.editor),
        )
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), previous)

    def test_page_navigation_and_end_update_scroll_position(self) -> None:
        self.editor.setPlainText(self._lines(300))
        self.editor.setFocus()
        self.app.processEvents()
        scrollbar = self.editor.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        QTest.keyClick(self.editor, Qt.Key.Key_PageUp)
        self.app.processEvents()
        self.assertLess(scrollbar.value(), scrollbar.maximum())

        before = scrollbar.value()
        QTest.keyClick(self.editor, Qt.Key.Key_PageDown)
        self.app.processEvents()
        self.assertGreaterEqual(scrollbar.value(), before)

        QTest.keyClick(self.editor, Qt.Key.Key_End)
        self.app.processEvents()
        self.assertEqual(scrollbar.value(), scrollbar.maximum())

    def test_pause_changes_scrolling_without_stopping_refresh_timer(self) -> None:
        widget = JobsOutputsWidget()
        widget.session = {"connected": True}
        widget.active_out = "/tmp/output.log"
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget._live_timer.start()

        widget._toggle_tail_pause()

        self.assertTrue(widget._tail_paused)
        self.assertTrue(widget._live_timer.isActive())
        self.assertFalse(widget.btn_tail_pause.isVisible())
        widget.shutdown()
        widget.deleteLater()

    @staticmethod
    def _run_async_immediately(_key, fn, on_success, **_kwargs) -> bool:
        on_success(fn())
        return True

    def test_ssh_poll_requests_last_200_lines_for_both_outputs(self) -> None:
        class FakeSSH:
            def __init__(self) -> None:
                self.commands = []

            def run(self, command, log_output=False):
                self.commands.append((command, log_output))
                return 0, f"content for {command}", ""

        ssh = FakeSSH()
        widget = JobsOutputsWidget()
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget.session = {"connected": True, "files": object(), "ssh": ssh}
        widget.active_out = "/tmp/output file.log"
        widget.active_err = "/tmp/error file.log"
        widget._start_async = self._run_async_immediately

        widget._poll_live()
        self.app.processEvents()

        self.assertEqual(len(ssh.commands), 2)
        self.assertTrue(all("tail -n 200 --" in command for command, _ in ssh.commands))
        self.assertTrue(all(log_output is False for _, log_output in ssh.commands))
        self.assertIn("content for", widget.txt_out.toPlainText())
        self.assertIn("content for", widget.txt_err.toPlainText())
        widget.shutdown()
        widget.deleteLater()

    def test_file_fallback_displays_only_last_200_lines(self) -> None:
        class FakeFiles:
            @staticmethod
            def read_text(_path):
                return "\n".join(f"line {index}" for index in range(250))

        widget = JobsOutputsWidget()
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)
        widget.session = {"connected": True, "files": FakeFiles()}
        widget.active_out = "/tmp/output.log"
        widget._start_async = self._run_async_immediately

        widget._poll_live()
        self.app.processEvents()

        lines = widget.txt_out.toPlainText().splitlines()
        self.assertEqual(len(lines), 200)
        self.assertEqual(lines[0], "line 50")
        self.assertNotIn("line 49", lines)
        self.assertEqual(lines[-1], "line 249")
        widget.shutdown()
        widget.deleteLater()


if __name__ == "__main__":
    unittest.main()
