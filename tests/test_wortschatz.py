import random
import tempfile
import unittest
from pathlib import Path

import wortschatz


class WortschatzTests(unittest.TestCase):
    def test_index_ignores_comments_and_invalid_lines(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            dictionary = data_dir / wortschatz.DICTIONARY_FILENAME
            index = data_dir / wortschatz.INDEX_FILENAME
            dictionary.write_text(
                "# DING dictionary\n"
                "kein Trennzeichen\n"
                "der Bildschirm {m} :: screen\n"
                "die Lösung {f} :: solution; answer\n",
                encoding="utf-8",
            )

            count = wortschatz.build_index(dictionary, index)

            self.assertEqual(count, 2)
            entries = {
                wortschatz.random_entry(data_dir, random.Random(seed))
                for seed in range(20)
            }
            self.assertEqual(
                entries,
                {
                    ("der Bildschirm {m}", "screen"),
                    ("die Lösung {f}", "solution; answer"),
                },
            )

    def test_plain_format(self):
        self.assertEqual(
            wortschatz.format_entry("arbeiten", "to work", use_color=False),
            "arbeiten — to work",
        )


if __name__ == "__main__":
    unittest.main()
