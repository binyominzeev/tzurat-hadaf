import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from layout import build_layout, check_main_font
from pilot import clean, marked_words, tokens, verse_page, verse_sections


def source(book, sections, ends, text):
    return {"book": book, "ref": book, "sections": sections, "toSections": ends,
            "versions": [{"text": text}]}


class VerseCommentaryTests(unittest.TestCase):
    def test_main_text_preserves_cantillation_but_matching_ignores_it(self):
        main = source("Genesis", ["1", "1"], ["1", "1"], "בְּרֵאשִׁ֖ית")
        page = verse_page(main, {}, "test", None)
        self.assertEqual(page["main"][0]["text"], "בְּרֵאשִׁ֖ית")
        self.assertEqual(page["main"][0]["norm"], tokens("בראשית")[0]["norm"])
        self.assertEqual(clean("בְּרֵאשִׁ֖ית"), "בְּרֵאשִׁית")

    def test_unavailable_selected_font_is_reported(self):
        with patch("layout.shutil.which", return_value="/usr/bin/typst"), \
             patch("layout.subprocess.run") as run:
            run.return_value.stdout = "SBL Hebrew\n"
            check_main_font("SBL Hebrew")
            with self.assertRaisesRegex(ValueError, "Taamey Ashkenaz"):
                check_main_font("Taamey Ashkenaz")

    def test_source_bold_spans_and_corrections_are_preserved(self):
        self.assertEqual(
            marked_words("<b>דיבור המתחיל.</b> (שגוי) [נכון] <strong>עוד</strong> סוף",
                         corrections=True),
            [("דיבור", True), ("המתחיל.", True), ("נכון", False),
             ("עוד", True), ("סוף", False)],
        )

    def test_numbers_and_bold_text_follow_verses_in_every_slot(self):
        main = source("Genesis", ["29", "25"], ["29", "27"], ["אחד", "שנים", "שלשה"])
        commentary = source("Rashi on Genesis", ["29", "25"], ["29", "27"], [
            ["<b>ראשון</b> פירוש", "<b>שני</b> פירוש"],
            [],
            ["<b>שלישי</b> פירוש"],
        ])
        sources = {role: (commentary, {"label": role}) for role in ("abudraham", "rashi", "vitry")}
        page = verse_page(main, sources, "test", None)
        with tempfile.TemporaryDirectory() as directory:
            data = build_layout(page, {}, Path(directory))
        self.assertEqual([word["v"] for word in data["main"]], ["25", "26", "27"])
        for stream in data["streams"].values():
            atoms = stream["atoms"]
            self.assertEqual([a["m"] for a in atoms if a["m"]], ["25", "27"])
            self.assertEqual([a["t"] for a in atoms if a["b"]], ["ראשון", "שני", "שלישי"])
            self.assertEqual([a["a"] for a in atoms if a["f"]], [0, 0, 2])

    def test_additional_commentary_has_its_own_bottom_stream(self):
        main = source("Genesis", ["1", "1"], ["1", "1"], "אחד")
        commentary = source("Rashi on Genesis", ["1", "1"], ["1", "1"], ["<b>אחד</b> פירוש"])
        extra = {"extra_1": {"label": "נוסף"}}
        page = verse_page(main, {"extra_1": (commentary, extra["extra_1"])}, "test", None)
        with tempfile.TemporaryDirectory() as directory:
            data = build_layout(page, {"additional_commentaries": extra}, Path(directory))
        self.assertEqual(data["bottom_streams"], ["B", "B1"])
        self.assertEqual(data["streams"]["B1"]["label"], "נוסף")
        self.assertEqual([atom["t"] for atom in data["streams"]["B1"]["atoms"]], ["אחד", "פירוש"])
        self.assertEqual(data["streams"]["B1"]["atoms"][0]["m"], "1")

    def test_unstructured_additional_commentary_flows_along_main_text(self):
        page = {"main": [{"text": str(i), "glue": False} for i in range(10)],
                "notes": [], "unit_notes": [], "variants": [],
                "additional_commentaries": {"extra_1": [("first", True), ("last", False)]}}
        with tempfile.TemporaryDirectory() as directory:
            data = build_layout(page, {"additional_commentaries": {"extra_1": {"label": "Extra"}}},
                                Path(directory))
        atoms = data["streams"]["B1"]["atoms"]
        self.assertEqual([(a["a"], a["b"]) for a in atoms], [(0, True), (5, False)])

    def test_multi_chapter_and_single_verse_ranges(self):
        main = source("Genesis", ["1", "30"], ["2", "2"], [["א", "ב"], ["ג", "ד"]])
        self.assertEqual([(c, v) for c, v, _ in verse_sections(main)],
                         [(1, 30), (1, 31), (2, 1), (2, 2)])
        single = source("Rashi on Genesis", ["2", "2"], ["2", "2"], ["<b>ד</b> ביאור"])
        page = verse_page(main, {"rashi": (single, {})}, "test", None)
        self.assertEqual(page["commentary"]["rashi"][0]["anchor_w"], 3)
        self.assertEqual(page["commentary"]["rashi"][0]["number"], "2")

    def test_entire_book_starts_at_first_chapter_and_verse(self):
        data = source("Genesis", [], [], [["א", "ב"], ["ג"]])
        self.assertEqual([(c, v) for c, v, _ in verse_sections(data)],
                         [(1, 1), (1, 2), (2, 1)])

    def test_different_base_book_is_rejected(self):
        main = source("Genesis", ["1", "1"], ["1", "1"], "א")
        commentary = source("Rashi on Exodus", ["1", "1"], ["1", "1"], ["ב"])
        with self.assertRaisesRegex(ValueError, "nem a főszöveghez tartozik"):
            verse_page(main, {"rashi": (commentary, {})}, "test", None)

    def test_missing_source_bold_is_reported_without_guessing(self):
        main = source("Genesis", ["1", "1"], ["1", "1"], "א")
        commentary = source("Rashi on Genesis", ["1", "1"], ["1", "1"], ["פירוש"])
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            page = verse_page(main, {"rashi": (commentary, {})}, "test", None)
        self.assertIn("nem jelöl félkövér kezdőszót", warning.getvalue())
        self.assertEqual(page["commentary"]["rashi"][0]["words"], [("פירוש", False)])


class PaginationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("typst") and shutil.which("pdftotext"),
                         "Typst és pdftotext szükséges")
    def test_long_additional_commentary_continues_without_ellipsis(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ("lib.typ", "measure.typ", "render.typ"):
                shutil.copy(root / name, work / name)
            out = work / "out"
            out.mkdir()
            page = {"main": [{"text": "main", "glue": False}], "notes": [],
                    "unit_notes": [], "variants": [], "commentary": {
                        "extra_1": [{"anchor_w": 0, "number": "1",
                                     "words": [("word", False)] * 1600}]}}
            cfg = {"layout": {"slots": {"right": "", "left": "", "bottom": ""}},
                   "additional_commentaries": {"extra_1": {"label": "Extra"}}}
            build_layout(page, cfg, out)
            result = subprocess.run(
                ["typst", "query", "measure.typ", "<pages>", "--field", "value", "--one"],
                cwd=work, capture_output=True, text=True, check=True,
            )
            pages = json.loads(result.stdout)
            self.assertTrue(any(page["mode"] == "tail" for page in pages))
            self.assertEqual(pages[-1]["cur"]["B1"], 1600)
            (out / "pages.json").write_text(json.dumps(pages), encoding="utf-8")
            subprocess.run(["typst", "compile", "render.typ", "out/page.pdf"],
                           cwd=work, capture_output=True, check=True)
            text = subprocess.run(["pdftotext", "out/page.pdf", "-"], cwd=work,
                                  capture_output=True, text=True, check=True).stdout
            self.assertEqual(text.count("word"), 1600)
            self.assertNotIn("(…)", text)

    @unittest.skipUnless(shutil.which("typst"), "Typst szükséges")
    def test_tablet_commentary_gets_own_pages_before_main_text_resumes(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for name in ("lib.typ", "measure.typ", "render.typ"):
                shutil.copy(root / name, work / name)
            out = work / "out"
            out.mkdir()
            page = {
                "main": [{"text": f"main{i}", "glue": False} for i in range(400)],
                "notes": [],
                "unit_notes": [],
                "variants": [],
                "commentary": {
                    "extra_1": [{
                        "anchor_w": 0,
                        "number": "1",
                        "words": [("comment", False)] * 1600,
                    }]
                },
            }
            cfg = {
                "layout": {
                    "tablet_mode": True,
                    "tablet_commentary": "extra_1",
                    "slots": {"right": "", "left": "", "bottom": ""},
                    "page": {"width_cm": 29.7, "height_cm": 21.0},
                    "main_size_pt": 30,
                    "side_size_pt": 20,
                },
                "additional_commentaries": {"extra_1": {"label": "Extra"}},
            }
            data = build_layout(page, cfg, out)
            self.assertTrue(data["tablet_mode"])
            self.assertEqual(data["tablet_stream"], "B1")

            result = subprocess.run(
                ["typst", "query", "measure.typ", "<pages>", "--field", "value", "--one"],
                cwd=work, capture_output=True, text=True, check=True,
            )
            pages = json.loads(result.stdout)
            modes = [entry["mode"] for entry in pages]
            self.assertEqual(modes[0], "tablet-main")
            next_main = modes.index("tablet-main", 1)
            self.assertGreater(next_main, 1)
            self.assertTrue(all(mode == "tablet-comment" for mode in modes[1:next_main]))
            self.assertEqual(pages[next_main]["a"], pages[0]["b"])
            self.assertEqual(pages[-1]["b"], 400)


if __name__ == "__main__":
    unittest.main()
