import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from layout import build_layout
from pilot import marked_words, verse_page, verse_sections


def source(book, sections, ends, text):
    return {"book": book, "ref": book, "sections": sections, "toSections": ends,
            "versions": [{"text": text}]}


class VerseCommentaryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
