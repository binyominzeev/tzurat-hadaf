import subprocess
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import app


class PreviewConfigurationTests(unittest.TestCase):
    def test_sample_mode_uses_matching_local_source(self):
        source = {
            "main": {
                "url": app.sample_sources["main"]["url"],
                "version": "hebrew",
            }
        }
        with patch.object(app, "sources", source), patch.object(app, "sample_mode", True):
            result = app.make_config()
        self.assertEqual(result["main"]["file"], app.sample_sources["main"]["file"])
        self.assertTrue(result["ui"]["sample_mode"])

    def test_sample_mode_rejects_mismatched_source(self):
        source = {"main": {"url": "https://www.sefaria.org/Genesis.1"}}
        with patch.object(app, "sources", source), patch.object(app, "sample_mode", True):
            with self.assertRaisesRegex(ValueError, "Nincs minta"):
                app.make_config()

    def test_live_mode_does_not_use_local_file(self):
        source = {"main": {**app.sample_sources["main"]}}
        with patch.object(app, "sources", source), patch.object(app, "sample_mode", False):
            result = app.make_config()
        self.assertNotIn("file", result["main"])
        self.assertFalse(result["ui"]["sample_mode"])


class SourcePlacementTests(unittest.TestCase):
    def test_prefers_role_slot_then_another_empty_slot(self):
        self.assertEqual(app.available_slot("abudraham", {"right": "", "left": "rashi", "bottom": ""}), "right")
        self.assertEqual(app.available_slot("abudraham", {"right": "rashi", "left": "", "bottom": ""}), "left")

    def test_does_not_replace_or_duplicate_sources(self):
        slots = {"right": "abudraham", "left": "rashi", "bottom": "vitry"}
        self.assertIsNone(app.available_slot("abudraham", slots))
        self.assertIsNone(app.available_slot("new", slots))
        self.assertIsNone(app.available_slot("main", {"right": "", "left": "", "bottom": ""}))

    def test_unplaced_source_can_be_added_without_overwriting_other_slot(self):
        slots = {"right": "", "left": "rashi", "bottom": ""}
        control = MagicMock()
        with (
            patch.object(app, "slot_values", slots),
            patch.object(app, "slot_controls", {"right": control}),
            patch.object(app, "sources", {"abudraham": {"label": "Chizkuni"}}),
            patch.object(app.ui, "notify"),
        ):
            self.assertEqual(app.place_source("abudraham"), "right")
        self.assertEqual(control.value, "abudraham")
        self.assertEqual(slots["left"], "rashi")


class PreviewErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_background_failure_notifies_in_preview_context(self):
        preview_area = MagicMock()
        label = MagicMock()
        log = MagicMock()
        result = subprocess.CompletedProcess([], 1, "403 Client Error", "")
        with (
            patch.object(app, "preview_revision", 1),
            patch.object(app, "preview_area", preview_area),
            patch.object(app, "preview_status_label", label),
            patch.object(app, "build_log", log),
            patch.object(app, "persist_config"),
            patch.object(app.run, "io_bound", new=AsyncMock(return_value=result)),
            patch.object(app.ui, "notify") as notify,
        ):
            await app.reflow_preview(1)
        preview_area.__enter__.assert_called_once()
        notify.assert_called_once()
        self.assertIn("nem frissült", label.text)
        self.assertIn("403", log.text)


if __name__ == "__main__":
    unittest.main()
