from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from truba_gui import __version__
from truba_gui.services.changelog import chronological_changelog
from truba_gui.ui.main_window import MainWindow


class StartupChangelogTests(unittest.TestCase):
    def test_changelog_sections_are_rendered_newest_first(self) -> None:
        text = "\n".join(
            [
                "# Changelog",
                "",
                "## v1.1.0",
                "- newest",
                "",
                "## v1.0.0",
                "- oldest",
            ]
        )

        rendered = chronological_changelog(text)

        self.assertLess(rendered.index("## v1.1.0"), rendered.index("## v1.0.0"))

    def test_startup_changelog_is_shown_once_per_version(self) -> None:
        stored_versions: list[str] = []

        def remember(version: str) -> str:
            stored_versions.append(version)
            return version

        class FakeWindow:
            def _show_changelog_dialog(self, text: str) -> None:
                shown_texts.append(text)

        shown_texts: list[str] = []

        with (
            patch(
                "truba_gui.ui.main_window.get_last_seen_changelog_version",
                side_effect=["1.1.0", __version__],
            ),
            patch("truba_gui.ui.main_window.set_last_seen_changelog_version", remember),
            patch(
                "truba_gui.ui.main_window.load_changelog_text",
                return_value="# Changelog\n\n## v1.1.0\n- old\n\n## v1.1.1\n- new",
            ),
        ):
            window = FakeWindow()
            MainWindow._show_startup_changelog_if_needed(window)
            MainWindow._show_startup_changelog_if_needed(window)

        self.assertEqual(len(shown_texts), 1)
        self.assertEqual(stored_versions, [__version__])


if __name__ == "__main__":
    unittest.main()
