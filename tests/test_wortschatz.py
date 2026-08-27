import io
import json
import random
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                wortschatz.random_entry(
                    data_dir,
                    random.Random(seed),
                    language="en",
                )
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

    def test_spanish_source_is_reversed_to_german_first(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            source = data_dir / "es-de"
            dictionary = data_dir / "de-es.txt"
            index = data_dir / "de-es.idx"
            source.write_text(
                "# Spanish-German dictionary\n"
                "casa :: Haus\n"
                "perro :: Hund\n",
                encoding="utf-8",
            )

            wortschatz._reverse_dictionary(source, dictionary)
            self.assertEqual(
                dictionary.read_text(encoding="utf-8"),
                "# Spanish-German dictionary\n"
                "Haus :: casa\n"
                "Hund :: perro\n",
            )
            self.assertEqual(wortschatz.build_index(dictionary, index), 2)
            self.assertIn(
                wortschatz.random_entry(
                    data_dir,
                    random.Random(0),
                    language="es",
                ),
                {("Haus", "casa"), ("Hund", "perro")},
            )

    def test_update_uses_language_specific_files_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)

            def fake_download(url, destination):
                self.assertIn("sourceforge", url)
                with tarfile.open(destination, "w:gz") as archive:
                    content = "mío :: mein\n".encode("latin-1")
                    member = tarfile.TarInfo("ger-esp.ding")
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
                return 14

            with patch.object(wortschatz, "_download_source", fake_download):
                count, size = wortschatz.update_dictionary(data_dir, language="es")

            self.assertEqual((count, size), (1, 14))
            self.assertTrue((data_dir / "de-es.txt").is_file())
            self.assertTrue((data_dir / "de-es.idx").is_file())
            self.assertFalse((data_dir / "de-en.txt").exists())
            metadata = json.loads(
                (data_dir / "metadata-de-es.json").read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["language"], "de-es")
            self.assertEqual(
                wortschatz.random_entry(data_dir, language="es"),
                ("mein", "mío"),
            )

    def test_stats_reports_selected_dictionary_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            dictionary = data_dir / "de-es.txt"
            index = data_dir / "de-es.idx"
            dictionary.write_text("mein :: mío\n", encoding="utf-8")
            wortschatz.build_index(dictionary, index)

            with patch("sys.stdout", new_callable=io.StringIO) as output:
                result = wortschatz.main(
                    ["--data-dir", str(data_dir), "stats", "--language", "es"]
                )

            self.assertEqual(result, 0)
            self.assertEqual(output.getvalue(), "Spanish dictionary: 1 entries.\n")

    def test_parser_accepts_language_before_or_after_update(self):
        self.assertEqual(
            wortschatz.create_parser().parse_args([]).language,
            "es",
        )
        self.assertEqual(
            wortschatz.create_parser().parse_args(["--language", "es"]).language,
            "es",
        )
        self.assertEqual(
            wortschatz.create_parser()
            .parse_args(["update", "--to", "es"])
            .language,
            "es",
        )

    def test_missing_dictionary_error_mentions_selected_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                wortschatz.WortschatzError,
                r"wortschatz update --language en",
            ):
                wortschatz.random_entry(Path(temporary), language="en")


if __name__ == "__main__":
    unittest.main()
