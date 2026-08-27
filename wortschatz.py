#!/usr/bin/env python3
"""Print a random German translation entry from a local dictionary."""

from __future__ import annotations

import argparse
import json
import os
import random
import struct
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, Tuple


DEFAULT_DICTIONARY_URL = (
    "https://ftp.tu-chemnitz.de/pub/Local/urz/ding/de-en/de-en.txt.zip"
)
DEFAULT_LANGUAGE = "es"
DICTIONARY_FILENAME = "de-en.txt"
INDEX_FILENAME = "de-en.idx"
METADATA_FILENAME = "metadata.json"
INDEX_MAGIC = b"WORTIDX1"
INDEX_HEADER = struct.Struct("<8sQQ")
INDEX_OFFSET = struct.Struct("<Q")
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_DICTIONARY_BYTES = 128 * 1024 * 1024


@dataclass(frozen=True)
class DictionarySpec:
    """Source and storage details for one German-to-target dictionary."""

    language: str
    name: str
    url: str
    source_filename: str
    archive: bool
    archive_format: str
    reverse_sides: bool
    license: str

    @property
    def dictionary_filename(self) -> str:
        return f"de-{self.language}.txt"

    @property
    def index_filename(self) -> str:
        return f"de-{self.language}.idx"

    @property
    def metadata_filename(self) -> str:
        # Keep the original metadata filename for existing DE-EN
        # installations, while giving other dictionaries their own metadata.
        if self.language == "en":
            return METADATA_FILENAME
        return f"metadata-de-{self.language}.json"


DICTIONARIES = {
    "en": DictionarySpec(
        language="en",
        name="English",
        url=DEFAULT_DICTIONARY_URL,
        source_filename="de-en.txt",
        archive=True,
        archive_format="zip",
        reverse_sides=False,
        license="GPL-2.0-or-later",
    ),
    "es": DictionarySpec(
        language="es",
        name="Spanish",
        url=(
            "https://sourceforge.net/projects/macding/files/"
            "german-spanish%20dictionary/ger-esp%20%28version%2013.05.05%29/"
            "ger-esp.tar.gz/download"
        ),
        source_filename="ger-esp.ding",
        archive=True,
        archive_format="tar.gz",
        reverse_sides=True,
        license=(
            "GPL-2.0-or-later, GFDL-1.2-or-later, "
            "CC BY-SA 1.0"
        ),
    ),
}
SUPPORTED_LANGUAGES = tuple(DICTIONARIES)


class WortschatzError(Exception):
    """A user-facing wortschatz error."""


def default_data_dir() -> Path:
    override = os.environ.get("WORTSCHATZ_DATA_DIR")
    if override:
        return Path(override).expanduser()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "wortschatz"

    return Path.home() / ".local" / "share" / "wortschatz"


def dictionary_spec(language: str = DEFAULT_LANGUAGE) -> DictionarySpec:
    try:
        return DICTIONARIES[language]
    except KeyError as error:
        choices = ", ".join(SUPPORTED_LANGUAGES)
        raise WortschatzError(
            f"unsupported target language {language!r}; choose one of: {choices}"
        ) from error


def _is_dictionary_entry(line: bytes) -> bool:
    stripped = line.lstrip()
    return bool(stripped and not stripped.startswith(b"#") and b"::" in line)


def build_index(dictionary_path: Path, index_path: Path) -> int:
    """Build a compact file of byte offsets for constant-time random access."""
    dictionary_size = dictionary_path.stat().st_size
    count = 0

    with dictionary_path.open("rb") as dictionary, index_path.open("w+b") as index:
        index.write(INDEX_HEADER.pack(INDEX_MAGIC, dictionary_size, 0))

        while True:
            offset = dictionary.tell()
            line = dictionary.readline()
            if not line:
                break
            if _is_dictionary_entry(line):
                index.write(INDEX_OFFSET.pack(offset))
                count += 1

        index.seek(0)
        index.write(INDEX_HEADER.pack(INDEX_MAGIC, dictionary_size, count))

    if count == 0:
        index_path.unlink(missing_ok=True)
        raise WortschatzError("the downloaded file contains no dictionary entries")

    return count


def _copy_limited(source: BinaryIO, destination: BinaryIO, limit: int) -> int:
    total = 0
    while True:
        chunk = source.read(1024 * 1024)
        if not chunk:
            return total
        total += len(chunk)
        if total > limit:
            raise WortschatzError(
                f"download exceeds the safety limit of {limit // (1024 * 1024)} MiB"
            )
        destination.write(chunk)


def _download_source(url: str, destination: Path) -> int:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "wortschatz-cli/0.1 "
                "(+https://github.com/Josgonmar/wortschatz-cli)"
            )
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            advertised_size = response.headers.get("Content-Length")
            if advertised_size and int(advertised_size) > MAX_DOWNLOAD_BYTES:
                raise WortschatzError("the dictionary source is unexpectedly large")
            with destination.open("wb") as source:
                return _copy_limited(response, source, MAX_DOWNLOAD_BYTES)
    except (urllib.error.URLError, TimeoutError) as error:
        raise WortschatzError(f"could not download the dictionary: {error}") from error


def _download_archive(url: str, destination: Path) -> int:
    """Backward-compatible name for the dictionary source downloader."""
    return _download_source(url, destination)


def _extract_dictionary(
    archive_path: Path,
    destination: Path,
    expected_filename: str = DICTIONARY_FILENAME,
    archive_format: str = "zip",
) -> None:
    if archive_format == "tar.gz":
        try:
            with tarfile.open(archive_path, "r:*") as archive:
                matches = [
                    member
                    for member in archive.getmembers()
                    if member.isfile() and Path(member.name).name == expected_filename
                ]
                if len(matches) != 1:
                    raise WortschatzError(
                        f"archive should contain exactly one {expected_filename} file"
                    )

                member = matches[0]
                if member.size > MAX_DICTIONARY_BYTES:
                    raise WortschatzError(
                        "the uncompressed dictionary is unexpectedly large"
                    )

                source = archive.extractfile(member)
                if source is None:
                    raise WortschatzError(
                        f"could not read {expected_filename} from the dictionary archive"
                    )
                with source, destination.open("wb") as output:
                    _copy_limited(source, output, MAX_DICTIONARY_BYTES)
            return
        except tarfile.ReadError as error:
            raise WortschatzError(
                "the downloaded dictionary is not a valid TAR archive"
            ) from error

    if archive_format != "zip":
        raise WortschatzError(f"unsupported dictionary archive format: {archive_format}")

    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                member
                for member in archive.infolist()
                if not member.is_dir()
                and Path(member.filename).name == expected_filename
            ]
            if len(matches) != 1:
                raise WortschatzError(
                    f"archive should contain exactly one {expected_filename} file"
                )

            member = matches[0]
            if member.file_size > MAX_DICTIONARY_BYTES:
                raise WortschatzError("the uncompressed dictionary is unexpectedly large")

            with archive.open(member) as source, destination.open("wb") as output:
                _copy_limited(source, output, MAX_DICTIONARY_BYTES)
    except zipfile.BadZipFile as error:
        raise WortschatzError("the downloaded dictionary is not a valid ZIP archive") from error


def _reverse_dictionary(source_path: Path, destination: Path) -> None:
    """Normalize a target-first DING list to the CLI's German-first format."""
    with source_path.open("rb") as source, destination.open("wb") as output:
        for line in source:
            content = line.rstrip(b"\r\n")
            line_ending = line[len(content) :]
            if _is_dictionary_entry(line):
                left, right = content.split(b"::", 1)
                content = right.strip() + b" :: " + left.strip()
            output.write(content + line_ending)


def _prepare_dictionary(
    source_path: Path,
    raw_dictionary_path: Path,
    dictionary_path: Path,
    spec: DictionarySpec,
) -> None:
    if spec.archive:
        _extract_dictionary(
            source_path,
            raw_dictionary_path,
            expected_filename=spec.source_filename,
            archive_format=spec.archive_format,
        )
    else:
        with source_path.open("rb") as source, raw_dictionary_path.open("wb") as output:
            _copy_limited(source, output, MAX_DICTIONARY_BYTES)

    if spec.reverse_sides:
        _reverse_dictionary(raw_dictionary_path, dictionary_path)
    else:
        os.replace(raw_dictionary_path, dictionary_path)


def update_dictionary(
    data_dir: Path,
    url: Optional[str] = None,
    language: str = DEFAULT_LANGUAGE,
) -> Tuple[int, int]:
    """Download, validate, index, and atomically install the dictionary."""
    spec = dictionary_spec(language)
    source_url = url if url is not None else spec.url
    data_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="update-", dir=data_dir) as temporary:
        temporary_dir = Path(temporary)
        source_path = temporary_dir / "dictionary-source"
        raw_dictionary_path = temporary_dir / "dictionary-raw.txt"
        dictionary_path = temporary_dir / spec.dictionary_filename
        index_path = temporary_dir / spec.index_filename

        download_size = _download_archive(source_url, source_path)
        _prepare_dictionary(
            source_path,
            raw_dictionary_path,
            dictionary_path,
            spec,
        )
        entry_count = build_index(dictionary_path, index_path)

        os.replace(dictionary_path, data_dir / spec.dictionary_filename)
        os.replace(index_path, data_dir / spec.index_filename)

    metadata = {
        "source": source_url,
        "language": f"de-{spec.language}",
        "source_language": "de",
        "target_language": spec.language,
        "license": spec.license,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "entries": entry_count,
    }
    metadata_path = data_dir / spec.metadata_filename
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=data_dir, delete=False
    ) as temporary_metadata:
        json.dump(metadata, temporary_metadata, indent=2, sort_keys=True)
        temporary_metadata.write("\n")
        temporary_metadata_path = Path(temporary_metadata.name)
    os.replace(temporary_metadata_path, metadata_path)

    return entry_count, download_size


def _read_index_header(
    index: BinaryIO,
    dictionary_size: int,
    language: str = DEFAULT_LANGUAGE,
) -> int:
    update_command = f"`wortschatz update --language {language}`"
    header = index.read(INDEX_HEADER.size)
    if len(header) != INDEX_HEADER.size:
        raise WortschatzError(f"dictionary index is truncated; run {update_command}")

    magic, indexed_size, entry_count = INDEX_HEADER.unpack(header)
    if magic != INDEX_MAGIC or indexed_size != dictionary_size or entry_count == 0:
        raise WortschatzError(f"dictionary index is stale; run {update_command}")

    expected_size = INDEX_HEADER.size + entry_count * INDEX_OFFSET.size
    index.seek(0, os.SEEK_END)
    if index.tell() != expected_size:
        raise WortschatzError(f"dictionary index is invalid; run {update_command}")

    return entry_count


def random_entry(
    data_dir: Path,
    generator: Optional[random.Random] = None,
    language: str = DEFAULT_LANGUAGE,
) -> Tuple[str, str]:
    spec = dictionary_spec(language)
    dictionary_path = data_dir / spec.dictionary_filename
    index_path = data_dir / spec.index_filename
    if not dictionary_path.is_file() or not index_path.is_file():
        raise WortschatzError(
            f"{spec.name} dictionary is not installed; run "
            f"`wortschatz update --language {spec.language}`"
        )

    chooser = generator if generator is not None else random.SystemRandom()
    dictionary_size = dictionary_path.stat().st_size

    with index_path.open("rb") as index:
        entry_count = _read_index_header(index, dictionary_size, spec.language)
        selection = chooser.randrange(entry_count)
        index.seek(INDEX_HEADER.size + selection * INDEX_OFFSET.size)
        packed_offset = index.read(INDEX_OFFSET.size)

    if len(packed_offset) != INDEX_OFFSET.size:
        raise WortschatzError(
            "dictionary index is truncated; "
            f"run `wortschatz update --language {spec.language}`"
        )

    (offset,) = INDEX_OFFSET.unpack(packed_offset)
    with dictionary_path.open("rb") as dictionary:
        dictionary.seek(offset)
        line = dictionary.readline().decode("utf-8", errors="replace").strip()

    try:
        german, translation = line.split("::", 1)
    except ValueError as error:
        raise WortschatzError("selected dictionary entry is malformed") from error

    return german.strip(), translation.strip()


def format_entry(german: str, translation: str, use_color: bool) -> str:
    if use_color:
        return f"\033[1;33m{german}\033[0m — {translation}"
    return f"{german} — {translation}"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wortschatz",
        description="Print a random German translation entry.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=default_data_dir(),
        help="dictionary directory (default: %(default)s)",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="disable ANSI color even when stdout is a terminal",
    )
    parser.add_argument(
        "--language",
        "--to",
        dest="language",
        choices=SUPPORTED_LANGUAGES,
        default=DEFAULT_LANGUAGE,
        metavar="CODE",
        help=f"translation target language (default: {DEFAULT_LANGUAGE})",
    )
    subcommands = parser.add_subparsers(dest="command")
    update = subcommands.add_parser("update", help="download and index the dictionary")
    update.add_argument(
        "--language",
        "--to",
        dest="language",
        choices=SUPPORTED_LANGUAGES,
        default=argparse.SUPPRESS,
        metavar="CODE",
        help=f"translation target language (default: {DEFAULT_LANGUAGE})",
    )
    update.add_argument(
        "--url",
        default=None,
        help="override the source archive or text-file URL",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = create_parser().parse_args(argv)
    data_dir = arguments.data_dir.expanduser()

    try:
        if arguments.command == "update":
            entry_count, download_size = update_dictionary(
                data_dir,
                arguments.url,
                arguments.language,
            )
            size_mib = download_size / (1024 * 1024)
            print(f"Installed {entry_count:,} entries ({size_mib:.1f} MiB download).")
            return 0

        german, translation = random_entry(data_dir, language=arguments.language)
        use_color = sys.stdout.isatty() and not arguments.plain and "NO_COLOR" not in os.environ
        print(format_entry(german, translation, use_color))
        return 0
    except (OSError, WortschatzError) as error:
        print(f"wortschatz: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
