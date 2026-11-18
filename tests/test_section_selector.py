import unittest
from unittest.mock import Mock, patch

import app


class TextIndexTests(unittest.TestCase):
    def test_complex_index_builds_refs_from_primary_names_and_default_nodes(self):
        response = Mock()
        response.json.return_value = {
            "title": "Chizkuni",
            "schema": {"nodes": [
                {"sharedTitle": "Introduction", "depth": 1},
                {"key": "other", "titles": [{"lang": "en", "text": "Genesis", "primary": True}],
                 "depth": 3},
                {"titles": [{"lang": "en", "text": "Exodus", "primary": True}],
                 "nodes": [{"default": True, "depth": 3},
                           {"sharedTitle": "Introduction", "depth": 1}]},
            ]},
        }
        with patch.object(app.requests, "get", return_value=response):
            refs = app.load_text_refs("Chizkuni")
        self.assertEqual(refs, [
            "Chizkuni, Introduction", "Chizkuni, Genesis",
            "Chizkuni, Exodus", "Chizkuni, Exodus, Introduction",
        ])
        self.assertEqual(
            app.build_sefaria_url(refs[1], "1:1", "1:10"),
            "https://www.sefaria.org/Chizkuni%2C_Genesis.1.1-10",
        )

    def test_simple_index_uses_canonical_title(self):
        response = Mock()
        response.json.return_value = {"title": "Genesis", "schema": {"depth": 2}}
        with patch.object(app.requests, "get", return_value=response):
            self.assertEqual(app.load_text_refs("Bereishit"), ["Genesis"])

    def test_title_with_standalone_presentation_omits_parent(self):
        response = Mock()
        response.json.return_value = {"title": "Collection", "schema": {"nodes": [
            {"depth": 2, "titles": [
                {"lang": "en", "text": "Independent", "primary": True, "presentation": "alone"}
            ]}
        ]}}
        with patch.object(app.requests, "get", return_value=response):
            self.assertEqual(app.load_text_refs("Collection"), ["Independent"])

    def test_invalid_index_is_reported(self):
        response = Mock()
        with patch.object(app.requests, "get", return_value=response):
            response.json.return_value = {"error": "No book"}
            with self.assertRaisesRegex(ValueError, "No book"):
                app.load_text_refs("Unknown")
            response.json.return_value = {"title": "Book", "schema": {"nodes": [{"depth": 2}]}}
            with self.assertRaisesRegex(ValueError, "nincs angol neve"):
                app.load_text_refs("Book")


class SectionShapeTests(unittest.TestCase):
    def test_chapter_lengths_come_from_selected_version(self):
        response = Mock()
        response.json.return_value = {
            "sectionNames": ["Chapter", "Verse", "Comment"],
            "addressTypes": ["Perek", "Pasuk", "Integer"],
            "versions": [{"text": [[["comment"], []], [["comment"]]]}],
        }
        with patch.object(app.requests, "get", return_value=response) as get:
            shape = app.load_section_shape("Rashi on Genesis", "hebrew")
        self.assertEqual(shape["counts"], [2, 1])
        self.assertEqual(shape["names"], ["Chapter", "Verse"])
        self.assertEqual(get.call_args.kwargs["headers"], {"User-Agent": "tzurat-hadaf"})
        response.raise_for_status.assert_called_once()

    def test_missing_version_and_unsupported_schema_are_reported(self):
        response = Mock()
        with patch.object(app.requests, "get", return_value=response):
            response.json.return_value = {"versions": []}
            with self.assertRaisesRegex(ValueError, "nincs elérhető"):
                app.load_section_shape("Genesis", "hebrew")
            response.json.return_value = {
                "versions": [{"text": [[1]]}],
                "sectionNames": ["Volume", "Paragraph"],
                "addressTypes": ["Unsupported", "Integer"],
            }
            with self.assertRaisesRegex(ValueError, "nem áll rendelkezésre"):
                app.load_section_shape("Example", "hebrew")

    def test_range_order_and_bounds(self):
        shape = {"names": ["Chapter", "Verse"], "talmud": False, "counts": [31, 25]}
        app.validate_section_range("1:31", "2:1", shape)
        app.validate_section_range("1:5", "1", shape)
        with self.assertRaisesRegex(ValueError, "előtt"):
            app.validate_section_range("2:1", "1:31", shape)
        with self.assertRaisesRegex(ValueError, "nem szerepel"):
            app.validate_section_range("1:1", "2:26", shape)
        with self.assertRaisesRegex(ValueError, "kezdőpontot"):
            app.validate_section_range("", "1:1", shape)

    def test_talmud_addresses_and_range(self):
        shape = {"names": ["Daf", "Line"], "talmud": True, "counts": [0, 0, 14, 19]}
        self.assertEqual(app.section_label(2, True), "2a")
        self.assertEqual(app.section_label(3, True), "2b")
        app.validate_section_range("2a:14", "2b:1", shape)
        with self.assertRaisesRegex(ValueError, "előtt"):
            app.validate_section_range("2b:1", "2a:14", shape)


if __name__ == "__main__":
    unittest.main()
