from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication, QTextEdit
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from truba_gui.ui.widgets.jobs_outputs_widget import (
    JobsOutputsWidget,
    _OutputFollowerWidget,
    _NavigableTextEdit,
)
from truba_gui.core.i18n import current_language, load_language


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

    def test_live_follow_preserves_horizontal_scroll_position(self) -> None:
        wide_lines = "\n".join(
            f"row {index} " + "\t".join(f"column-{column:02d}" for column in range(40))
            for index in range(80)
        )
        self.editor.resize(420, 140)
        self.editor.setLineWrapMode(QTextEdit.NoWrap)
        JobsOutputsWidget._set_live_text(
            self.editor,
            wide_lines,
            follow_latest=True,
        )
        self.app.processEvents()

        horizontal = self.editor.horizontalScrollBar()
        vertical = self.editor.verticalScrollBar()
        self.assertGreater(horizontal.maximum(), 0)
        horizontal.setValue(horizontal.maximum() // 2)
        previous_horizontal = horizontal.value()

        JobsOutputsWidget._set_live_text(
            self.editor,
            wide_lines + "\nnew row with\twide\tcolumns",
            follow_latest=True,
        )
        self.app.processEvents()

        self.assertEqual(vertical.value(), vertical.maximum())
        self.assertEqual(horizontal.value(), previous_horizontal)

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

    def test_focus_job_can_bind_outputs_without_switching_subtab(self) -> None:
        class FakeFiles:
            @staticmethod
            def read_text(_path):
                return "\n".join(
                    [
                        "#!/bin/bash",
                        "#SBATCH -J demo",
                        "#SBATCH -o logs/%x_%j.out",
                        "#SBATCH -e logs/%x_%j.err",
                    ]
                )

        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": FakeFiles()}
        widget.section_tabs.setCurrentWidget(widget.details_tab)

        with (
            patch.object(widget, "refresh_jobs"),
            patch.object(widget, "refresh_sacct"),
            patch.object(widget, "_poll_live"),
        ):
            widget.focus_job(
                "12345",
                "/work/job.slurm",
                switch_to_outputs=False,
            )

        self.assertIs(widget.section_tabs.currentWidget(), widget.details_tab)
        self.assertEqual(widget.active_out, "/work/logs/demo_12345.out")
        self.assertEqual(widget.active_err, "/work/logs/demo_12345.err")
        widget.shutdown()
        widget.deleteLater()

    def test_output_path_edit_rebinds_followed_file(self) -> None:
        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": object()}
        widget.section_tabs.setCurrentWidget(widget.outputs_tab)

        with patch.object(widget, "_poll_live") as poll_live:
            widget.open_in_output_slot(0, "/work/old.out")
            widget.path_out.setText("/work/new.out")
            widget.path_out.returnPressed.emit()

        self.assertEqual(widget.active_out, "/work/new.out")
        self.assertEqual(widget.path_out.text(), "/work/new.out")
        self.assertEqual(widget.txt_out.toPlainText(), "")
        self.assertGreaterEqual(poll_live.call_count, 2)
        widget.shutdown()
        widget.deleteLater()

    def test_output_text_views_use_fixed_tab_aligned_terminal_style(self) -> None:
        widget = JobsOutputsWidget()
        follower = _OutputFollowerWidget()

        try:
            for text_view in (
                widget.jobs_text,
                widget.txt_out,
                widget.txt_err,
                follower.txt_out,
                follower.txt_err,
            ):
                self.assertEqual(text_view.lineWrapMode(), QTextEdit.NoWrap)
                expected_tab_width = (
                    QFontMetrics(text_view.font()).horizontalAdvance(" ") * 8
                )
                self.assertEqual(text_view.tabStopDistance(), expected_tab_width)
        finally:
            follower.shutdown()
            follower.deleteLater()
            widget.shutdown()
            widget.deleteLater()

    def test_open_in_output_tab_creates_independent_follower(self) -> None:
        class FakeFiles:
            @staticmethod
            def listdir_entries(_path):
                return []

        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": FakeFiles()}

        with patch.object(_OutputFollowerWidget, "_poll_live"):
            widget.open_in_output_tab(1, "/work/logs/job.err")

        follower = widget.section_tabs.widget(widget.section_tabs.count() - 1)
        self.assertIsInstance(follower, _OutputFollowerWidget)
        self.assertIs(widget.section_tabs.currentWidget(), follower)
        self.assertEqual(follower.active_err, "/work/logs/job.err")
        self.assertEqual(follower.path_err.text(), "/work/logs/job.err")
        self.assertEqual(widget.active_err, "")
        widget.shutdown()
        widget.deleteLater()

    def test_follow_tabs_can_be_closed_without_closing_base_tabs(self) -> None:
        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": object()}

        try:
            with patch.object(_OutputFollowerWidget, "_poll_live"):
                widget.open_in_output_tab(0, "/work/logs/job.out")

            self.assertEqual(widget.section_tabs.count(), 4)
            choices = widget._output_target_choices()
            self.assertEqual(len(choices), 1)
            self.assertEqual(choices[0][0], "tab:1")

            widget.section_tabs.tabCloseRequested.emit(0)
            self.assertEqual(widget.section_tabs.count(), 4)

            follower = widget.section_tabs.widget(3)
            with patch.object(follower, "shutdown", wraps=follower.shutdown) as shutdown:
                widget.section_tabs.tabCloseRequested.emit(3)
                shutdown.assert_called_once()

            self.assertEqual(widget.section_tabs.count(), 3)
            self.assertEqual(widget._output_target_choices(), [])
            self.assertEqual(widget._follow_tabs, [])
        finally:
            widget.shutdown()
            widget.deleteLater()

    def test_focus_job_defaults_to_new_lower_tabs_without_overwriting_outputs(self) -> None:
        class FakeFiles:
            @staticmethod
            def read_text(_path):
                return "\n".join(
                    [
                        "#SBATCH --job-name=demo",
                        "#SBATCH --output=logs/%x-%j.out",
                        "#SBATCH --error=logs/%x-%j.err",
                    ]
                )

        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": FakeFiles()}

        try:
            with (
                patch.object(widget, "refresh_jobs"),
                patch.object(widget, "refresh_sacct"),
                patch.object(_OutputFollowerWidget, "_poll_live"),
            ):
                widget.open_in_output_slot(0, "/work/logs/old.out")
                widget.focus_job(
                    "123",
                    "/work/job.slurm",
                    follow_mode="new_tabs_split",
                )

            self.assertEqual(widget.active_out, "/work/logs/old.out")
            self.assertEqual(widget.section_tabs.count(), 4)
            follower = widget.section_tabs.widget(3)
            self.assertIsInstance(follower, _OutputFollowerWidget)
            self.assertIs(widget.section_tabs.currentWidget(), follower)
            self.assertEqual(follower.active_out, "/work/logs/demo-123.out")
            self.assertEqual(follower.active_err, "/work/logs/demo-123.err")
            self.assertEqual(follower.path_out.text(), "/work/logs/demo-123.out")
            self.assertEqual(follower.path_err.text(), "/work/logs/demo-123.err")
        finally:
            widget.shutdown()
            widget.deleteLater()

    def test_focus_job_can_open_combined_or_split_follow_windows(self) -> None:
        class FakeFiles:
            @staticmethod
            def read_text(_path):
                return "\n".join(
                    [
                        "#SBATCH --output=job.out",
                        "#SBATCH --error=job.err",
                    ]
                )

        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": FakeFiles()}

        try:
            with (
                patch.object(widget, "refresh_jobs"),
                patch.object(widget, "refresh_sacct"),
                patch.object(_OutputFollowerWidget, "_poll_live"),
            ):
                widget.focus_job(
                    "10",
                    "/work/job.slurm",
                    follow_mode="new_window_combined",
                )
                self.assertEqual(len(widget._follow_windows), 1)
                combined = widget._follow_windows[0].centralWidget()
                self.assertEqual(combined.active_out, "/work/job.out")
                self.assertEqual(combined.active_err, "/work/job.err")

                widget.focus_job(
                    "11",
                    "/work/job.slurm",
                    follow_mode="new_windows_split",
                )

            self.assertEqual(len(widget._follow_windows), 3)
            split_out = widget._follow_windows[1].centralWidget()
            split_err = widget._follow_windows[2].centralWidget()
            self.assertEqual(split_out.active_out, "/work/job.out")
            self.assertEqual(split_err.active_err, "/work/job.err")
            self.assertTrue(split_out.out_box.isVisible())
            self.assertFalse(split_out.err_box.isVisible())
            self.assertFalse(split_err.out_box.isVisible())
            self.assertTrue(split_err.err_box.isVisible())
        finally:
            for window in list(widget._follow_windows):
                window.close()
            widget.shutdown()
            widget.deleteLater()

    def test_single_file_follower_hides_second_output_panel(self) -> None:
        widget = _OutputFollowerWidget()
        widget.set_session({"connected": True, "files": object()})

        with patch.object(widget, "_poll_live"):
            widget.set_single_file_mode("/work/logs/only.log")

        self.assertEqual(widget.active_out, "/work/logs/only.log")
        self.assertEqual(widget.path_out.text(), "/work/logs/only.log")
        self.assertFalse(widget.err_box.isVisible())
        self.assertFalse(widget.lbl_script.isVisible())
        widget.shutdown()
        widget.deleteLater()

    def test_follower_path_edit_rebinds_followed_file(self) -> None:
        widget = _OutputFollowerWidget()
        widget.set_session({"connected": True, "files": object()})

        with patch.object(widget, "_poll_live") as poll_live:
            widget.open_in_output_slot(1, "/work/old.err")
            widget.path_err.setText("/work/new.err")
            widget.path_err.returnPressed.emit()

        self.assertEqual(widget.active_err, "/work/new.err")
        self.assertEqual(widget.path_err.text(), "/work/new.err")
        self.assertEqual(widget.txt_err.toPlainText(), "")
        self.assertGreaterEqual(poll_live.call_count, 2)
        widget.shutdown()
        widget.deleteLater()

    def test_follow_windows_are_real_top_level_windows(self) -> None:
        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": object()}

        try:
            with patch.object(_OutputFollowerWidget, "_poll_live"):
                widget.open_in_output_window(0, "/work/logs/window.out")
                widget.open_file_follow_window("/work/logs/only.log")

            self.assertEqual(len(widget._follow_windows), 2)
            for window in widget._follow_windows:
                self.assertIsNone(window.parent())
                self.assertTrue(window.isWindow())
        finally:
            for window in list(widget._follow_windows):
                window.close()
            widget.shutdown()
            widget.deleteLater()

    def test_numbered_follow_targets_can_receive_existing_menu_assignments(self) -> None:
        previous_language = current_language()
        load_language("en")
        widget = JobsOutputsWidget()
        widget.session = {"connected": True, "files": object()}

        try:
            with patch.object(_OutputFollowerWidget, "_poll_live"):
                widget.open_in_output_window(0, "/work/logs/window.out")
                widget.open_in_output_tab(1, "/work/logs/tab.err")
                choices = widget._output_target_choices()

                self.assertEqual(
                    choices,
                    [("window:1", "Window 1"), ("tab:1", "Tab 1")],
                )

                widget.open_in_existing_follower(
                    "window:1",
                    1,
                    "/work/logs/reassigned.err",
                )
                widget.open_in_existing_follower(
                    "tab:1",
                    0,
                    "/work/logs/reassigned.out",
                )

            window_follower = widget._follow_targets["window:1"]
            tab_follower = widget._follow_targets["tab:1"]
            self.assertEqual(window_follower.active_err, "/work/logs/reassigned.err")
            self.assertEqual(tab_follower.active_out, "/work/logs/reassigned.out")
            for window in list(widget._follow_windows):
                window.close()
            widget.shutdown()
            widget.deleteLater()
        finally:
            load_language(previous_language)


if __name__ == "__main__":
    unittest.main()
