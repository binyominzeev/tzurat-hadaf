import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from pilot import fetch, fetch_verse_commentary


class FetchTests(unittest.TestCase):
    def test_text_request_identifies_application_and_is_cached(self):
        response = Mock()
        response.json.return_value = {"versions": [{"text": ["בראשית", "ברא"]}]}
        source = {"url": "https://www.sefaria.org/Genesis.1.1-5", "version": "hebrew"}
        with tempfile.TemporaryDirectory() as directory, patch("requests.get", return_value=response) as get:
            cache = Path(directory)
            self.assertEqual(fetch(source, cache), "בראשית ברא")
            self.assertEqual(fetch(source, cache), "בראשית ברא")
        get.assert_called_once_with(
            "https://www.sefaria.org/api/v3/texts/Genesis.1.1-5",
            params={"version": "hebrew"},
            headers={"User-Agent": "tzurat-hadaf"},
            timeout=30,
        )
        response.raise_for_status.assert_called_once()

    def test_failed_response_is_not_cached(self):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
        source = {"url": "https://www.sefaria.org/Genesis.1.1-5"}
        with tempfile.TemporaryDirectory() as directory, patch("requests.get", return_value=response):
            cache = Path(directory)
            with self.assertRaises(requests.HTTPError):
                fetch(source, cache)
            self.assertEqual(list(cache.iterdir()), [])

    def test_missing_verse_commentary_requires_confirmed_parent_book(self):
        response = Mock(status_code=404)
        response.json.return_value = {"error": "We have no text for Rashi on Genesis 1:1-2."}
        error = requests.HTTPError(response=response)
        parent = {"book": "Rashi on Genesis", "sectionNames": ["Chapter", "Verse", "Comment"],
                  "versions": [{"text": [["existing"]]}]}
        main = {"book": "Genesis", "sections": ["1", "1"], "toSections": ["1", "2"]}
        source = {"url": "https://www.sefaria.org/Rashi_on_Genesis.1.1-2"}
        with patch("pilot.fetch_data", side_effect=[error, parent]) as get:
            data, missing = fetch_verse_commentary(source, main)
        self.assertTrue(missing)
        self.assertEqual(data["versions"][0]["text"], [])
        self.assertEqual(data["sections"], main["sections"])
        self.assertEqual(get.call_args_list[1].args[0]["url"], "https://www.sefaria.org/Rashi_on_Genesis")

    def test_other_404_errors_are_not_treated_as_empty_commentary(self):
        response = Mock(status_code=404)
        response.json.return_value = {"error": "Unknown reference"}
        error = requests.HTTPError(response=response)
        with patch("pilot.fetch_data", side_effect=error):
            with self.assertRaises(requests.HTTPError):
                fetch_verse_commentary({"url": "https://www.sefaria.org/Bad.1.1"},
                                       {"book": "Genesis"})
