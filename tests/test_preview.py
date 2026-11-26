import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import app


class PreviewConfigurationTests(unittest.TestCase):
    def test_additional_sources_are_saved_separately_and_preserved_in_stack(self):
        source = {
            "main": {"url": "https://www.sefaria.org/Genesis.1.1"},
            "extra_1": {"url": "https://www.sefaria.org/Rashi_on_Genesis.1.1",
                        "label": "פירוש נוסף"},
        }
        with patch.object(app, "sources", source), patch.object(app, "sample_mode", False):
            result = app.make_config()
        self.assertEqual(result["additional_commentaries"]["extra_1"]["label"], "פירוש נוסף")
        self.assertEqual(result["stacks"][app.active_stack]["sources"]["extra_1"]["label"], "פירוש נוסף")
        self.assertNotIn("extra_1", result)

    def test_extra_source_keys_do_not_overwrite_existing_sources(self):
        self.assertEqual(app.extra_source_key({"extra_1": {}, "extra_3": {}}), "extra_2")

    def test_main_font_is_saved_separately_from_commentary_fonts(self):
        settings = app.initial_settings({"layout": {"main_font": "SBL Hebrew",
                                                   "fonts": ["David Libre"]}})
        with patch.object(app, "settings", settings):
            result = app.make_config()
        self.assertEqual(result["layout"]["main_font"], "SBL Hebrew")
        self.assertEqual(result["layout"]["fonts"], ["David Libre"])

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


class LayoutPresetTests(unittest.TestCase):
    def test_tablet_preset_applies_and_print_preset_restores_page_and_font_sizes(self):
        settings = app.initial_settings({})
        page_controls = {key: MagicMock() for key in ("page_width", "page_height")}
        layout_controls = {key: MagicMock() for key in ("main_size_pt", "side_size_pt")}
        orientation = MagicMock()
        preset = MagicMock()

        with (
            patch.object(app, "settings", settings),
            patch.object(app, "numeric_controls", page_controls),
            patch.object(app, "layout_controls", layout_controls),
            patch.object(app, "orientation_switch", orientation),
            patch.object(app, "preset_control", preset),
            patch.object(app, "render_preview") as render_preview,
            patch.object(app, "schedule_preview_reflow") as schedule_preview_reflow,
        ):
            app.set_layout_preset("tablet")
            self.assertEqual(
                (settings["page_width"], settings["page_height"]), (29.7, 21.0)
            )
            self.assertEqual(
                (settings["main_size_pt"], settings["side_size_pt"]), (30, 20)
            )
            self.assertFalse(settings["tablet_mode"])
            app.set_layout_preset("print")

        self.assertEqual(
            (settings["page_width"], settings["page_height"]), (21.0, 29.7)
        )
        self.assertEqual(
            (settings["main_size_pt"], settings["side_size_pt"]), (13, 8)
        )
        self.assertFalse(settings["tablet_mode"])
        for control in (*page_controls.values(), *layout_controls.values()):
            control.update.assert_called()
        self.assertEqual(render_preview.call_count, 2)
        self.assertEqual(schedule_preview_reflow.call_count, 2)


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


class LivePreviewTests(unittest.TestCase):
    def test_font_buttons_use_shared_settings_and_respect_limits(self):
        settings = app.initial_settings({})
        class Control:
            @property
            def value(self):
                return settings["main_size_pt"]

            @value.setter
            def value(self, value):
                app.set_numeric("main_size_pt", value)

            def update(self):
                pass

        with (
            patch.object(app, "settings", settings),
            patch.object(app, "layout_controls", {"main_size_pt": Control()}),
            patch.object(app, "render_preview") as render,
            patch.object(app, "schedule_preview_reflow") as reflow,
        ):
            app.adjust_preview_font({"key": "main_size_pt", "delta": 1})
            self.assertEqual(settings["main_size_pt"], 14)
            settings["main_size_pt"] = 32
            app.adjust_preview_font({"key": "main_size_pt", "delta": 1})
            app.adjust_preview_font({"key": "invalid", "delta": 1})
        render.assert_called_once()
        reflow.assert_called_once()

    def test_drag_swaps_occupied_slots_and_updates_controls(self):
        slots = {"right": "abudraham", "left": "rashi", "bottom": ""}
        controls = {slot: MagicMock() for slot in slots}
        with (
            patch.object(app, "slot_values", slots),
            patch.object(app, "slot_controls", controls),
            patch.object(app, "refresh_source_assignments") as refresh,
            patch.object(app, "render_preview") as render,
            patch.object(app, "schedule_preview_reflow") as reflow,
        ):
            app.move_preview_slot({"source": "right", "target": "left"})
        self.assertEqual(slots, {"right": "rashi", "left": "abudraham", "bottom": ""})
        self.assertEqual(controls["right"].value, "rashi")
        self.assertEqual(controls["left"].value, "abudraham")
        refresh.assert_called_once()
        render.assert_called_once()
        reflow.assert_called_once()

    def test_drag_to_empty_slot_and_invalid_drag(self):
        slots = {"right": "abudraham", "left": "", "bottom": ""}
        controls = {slot: MagicMock() for slot in slots}
        with (
            patch.object(app, "slot_values", slots),
            patch.object(app, "slot_controls", controls),
            patch.object(app, "refresh_source_assignments"),
            patch.object(app, "render_preview"),
            patch.object(app, "schedule_preview_reflow") as reflow,
        ):
            app.move_preview_slot({"source": "right", "target": "bottom"})
            app.move_preview_slot({"source": "right", "target": "left"})
            app.move_preview_slot({"source": "invalid", "target": "left"})
        self.assertEqual(slots, {"right": "", "left": "", "bottom": "abudraham"})
        reflow.assert_called_once()

    def test_reflow_requests_layout_without_rendering_pdf(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        with patch.object(app.subprocess, "run", return_value=completed) as run:
            app.generate_preview_layout()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[1].args[0][-1], "--preview-only")

    def test_preview_uses_source_content_after_moving_slots(self):
        pages = [{"a": 0, "b": 1, "top": [{"k": "R", "f": 0, "t": 1},
                                               {"k": "L", "f": 0, "t": 1}], "rs": []}]
        layout = {"main": [{"t": "main"}], "streams": {
            "R": {"atoms": [{"t": "right text"}]},
            "L": {"atoms": [{"t": "left text"}]},
        }}
        sources = {"main": {}, "abudraham": {}, "rashi": {}}
        with (
            patch.object(app, "preview_pages", pages),
            patch.object(app, "preview_layout", layout),
            patch.object(app, "preview_sources", sources),
            patch.object(app, "sources", sources),
            patch.object(app, "preview_slots", {"right": "abudraham", "left": "rashi", "bottom": ""}),
            patch.object(app, "slot_values", {"right": "rashi", "left": "abudraham", "bottom": ""}),
        ):
            content = app.page_preview_content(0)
        self.assertEqual(content["right"], "left text")
        self.assertEqual(content["left"], "right text")

    def test_flow_preview_shows_each_segment_in_its_physical_column(self):
        pages = [{"a": 0, "b": 1, "mode": "flow",
                  "top": [{"k": "R", "f": 0, "t": 1}, {"k": "R", "f": 1, "t": 2}], "rs": []}]
        layout = {"main": [{"t": "main"}], "streams": {
            "R": {"atoms": [{"t": "first"}, {"t": "second"}]},
        }}
        sources = {"main": {}, "abudraham": {}}
        slots = {"right": "abudraham", "left": "", "bottom": ""}
        with (
            patch.object(app, "preview_pages", pages),
            patch.object(app, "preview_layout", layout),
            patch.object(app, "preview_sources", sources),
            patch.object(app, "sources", sources),
            patch.object(app, "preview_slots", slots),
            patch.object(app, "slot_values", slots),
        ):
            content = app.page_preview_content(0)
        self.assertEqual((content["right"], content["left"]), ("first", "second"))

    def test_preview_rejects_cached_pages_for_other_sources(self):
        slots = {"right": "", "left": "", "bottom": ""}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            out.mkdir()
            (out / "pages.json").write_text(json.dumps([{"a": 0, "b": 1}]))
            (out / "layout.json").write_text(json.dumps({
                "main": [{"t": "old"}], "slots": slots,
                "source_config": {"main": {"url": "old", "version": "hebrew"}},
            }))
            with (
                patch.object(app, "ROOT", Path(directory)),
                patch.object(app, "sources", {"main": {"url": "new"}}),
                patch.object(app, "slot_values", slots),
                patch.object(app, "preview_pages", []),
                patch.object(app, "preview_layout", {}),
                patch.object(app, "preview_page_index", 0),
            ):
                self.assertFalse(app.load_preview_pages())
                self.assertEqual(app.preview_pages, [])

    def test_stale_startup_cache_is_reported_as_reflow_not_error(self):
        slots = {"right": "", "left": "", "bottom": ""}
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"
            out.mkdir()
            (out / "pages.json").write_text(json.dumps([{"a": 0, "b": 1}]))
            (out / "layout.json").write_text(json.dumps({
                "main": [{"t": "old"}], "slots": slots,
                "source_config": {"main": {"url": "old", "version": "hebrew"}},
            }))
            with (
                patch.object(app, "ROOT", Path(directory)),
                patch.object(app, "sources", {"main": {"url": "new"}}),
                patch.object(app, "slot_values", slots),
                patch.object(app, "preview_pages", []),
                patch.object(app, "preview_layout", {}),
                patch.object(app, "preview_page_index", 0),
                patch("builtins.print") as log,
            ):
                self.assertFalse(app.load_preview_pages(startup=True))
            self.assertIn("újraszámolódik", log.call_args.args[0])


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


class BuildProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_build_output_updates_status_and_log_as_stages_run(self):
        class Output:
            def __init__(self, lines):
                self.lines = iter(lines)

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self.lines)
                except StopIteration:
                    raise StopAsyncIteration

        process = MagicMock()
        process.stdout = Output(
            [
                b"==> 1/2 Adatok letoltesenek kezdete\n",
                b"==> 2/2 Tordeles es PDF\n",
                "==> Mérés és oldalbeosztás\n".encode("utf-8"),
                b"    12 oldal, 30 mp\n",
                "==> PDF renderelése\n".encode("utf-8"),
            ]
        )
        process.wait = AsyncMock(return_value=0)
        status = MagicMock()
        log = MagicMock()
        log.text = ""

        with (
            patch.object(app, "status_label", status),
            patch.object(app, "build_log", log),
            patch.object(app.asyncio, "create_subprocess_exec", new=AsyncMock(return_value=process)),
        ):
            result = await app.run_build_process()

        self.assertEqual(result, 0)
        self.assertEqual(
            status.text,
            "Oldalbeosztás kész (12 oldal); a PDF renderelése folyamatban…",
        )
        self.assertIn("12 oldal", log.text)
        self.assertEqual(log.update.call_count, 5)
        self.assertEqual(status.update.call_count, 5)


if __name__ == "__main__":
    unittest.main()
