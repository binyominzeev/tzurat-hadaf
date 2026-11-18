import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from pilot import fetch


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
