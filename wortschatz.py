#!/usr/bin/env python3
"""Print a random German-English entry from a local DING dictionary."""

from __future__ import annotations

import argparse
import json
import os
import random
import struct
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Optional, Sequence, Tuple


DEFAULT_DICTIONARY_URL = (
    "https://ftp.tu-chemnitz.de/pub/Local/urz/ding/de-en/de-en.txt.zip"
)
DICTIONARY_FILENAME = "de-en.txt"
INDEX_FILENAME = "de-en.idx"
METADATA_FILENAME = "metadata.json"
INDEX_MAGIC = b"WORTIDX1"
INDEX_HEADER = struct.Struct("<8sQQ")
INDEX_OFFSET = struct.Struct("<Q")
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
MAX_DICTIONARY_BYTES = 128 * 1024 * 1024


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


def _download_archive(url: str, destination: Path) -> int:
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
                raise WortschatzError("the dictionary archive is unexpectedly large")
            with destination.open("wb") as archive:
                return _copy_limited(response, archive, MAX_DOWNLOAD_BYTES)
    except (urllib.error.URLError, TimeoutError) as error:
        raise WortschatzError(f"could not download the dictionary: {error}") from error


def _extract_dictionary(archive_path: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            matches = [
                member
                for member in archive.infolist()
                if not member.is_dir() and Path(member.filename).name == DICTIONARY_FILENAME
            ]
            if len(matches) != 1:
                raise WortschatzError(
                    f"archive should contain exactly one {DICTIONARY_FILENAME} file"
                )

            member = matches[0]
            if member.file_size > MAX_DICTIONARY_BYTES:
                raise WortschatzError("the uncompressed dictionary is unexpectedly large")

            with archive.open(member) as source, destination.open("wb") as output:
                _copy_limited(source, output, MAX_DICTIONARY_BYTES)
    except zipfile.BadZipFile as error:
        raise WortschatzError("the downloaded dictionary is not a valid ZIP archive") from error


def update_dictionary(data_dir: Path, url: str) -> Tuple[int, int]:
    """Download, validate, index, and atomically install the dictionary."""
    data_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="update-", dir=data_dir) as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / "dictionary.zip"
        dictionary_path = temporary_dir / DICTIONARY_FILENAME
        index_path = temporary_dir / INDEX_FILENAME

        download_size = _download_archive(url, archive_path)
        _extract_dictionary(archive_path, dictionary_path)
        entry_count = build_index(dictionary_path, index_path)

        os.replace(dictionary_path, data_dir / DICTIONARY_FILENAME)
        os.replace(index_path, data_dir / INDEX_FILENAME)

    metadata = {
        "source": url,
        "license": "GPL-2.0-or-later",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "entries": entry_count,
    }
    metadata_path = data_dir / METADATA_FILENAME
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=data_dir, delete=False
    ) as temporary_metadata:
        json.dump(metadata, temporary_metadata, indent=2, sort_keys=True)
        temporary_metadata.write("\n")
        temporary_metadata_path = Path(temporary_metadata.name)
    os.replace(temporary_metadata_path, metadata_path)

    return entry_count, download_size


def _read_index_header(index: BinaryIO, dictionary_size: int) -> int:
    header = index.read(INDEX_HEADER.size)
    if len(header) != INDEX_HEADER.size:
        raise WortschatzError("dictionary index is truncated; run `wortschatz update`")

    magic, indexed_size, entry_count = INDEX_HEADER.unpack(header)
    if magic != INDEX_MAGIC or indexed_size != dictionary_size or entry_count == 0:
        raise WortschatzError("dictionary index is stale; run `wortschatz update`")

    expected_size = INDEX_HEADER.size + entry_count * INDEX_OFFSET.size
    index.seek(0, os.SEEK_END)
    if index.tell() != expected_size:
        raise WortschatzError("dictionary index is invalid; run `wortschatz update`")

    return entry_count


def random_entry(data_dir: Path, generator: Optional[random.Random] = None) -> Tuple[str, str]:
    dictionary_path = data_dir / DICTIONARY_FILENAME
    index_path = data_dir / INDEX_FILENAME
    if not dictionary_path.is_file() or not index_path.is_file():
        raise WortschatzError("dictionary is not installed; run `wortschatz update`")

    chooser = generator if generator is not None else random.SystemRandom()
    dictionary_size = dictionary_path.stat().st_size

    with index_path.open("rb") as index:
        entry_count = _read_index_header(index, dictionary_size)
        selection = chooser.randrange(entry_count)
        index.seek(INDEX_HEADER.size + selection * INDEX_OFFSET.size)
        packed_offset = index.read(INDEX_OFFSET.size)

    if len(packed_offset) != INDEX_OFFSET.size:
        raise WortschatzError("dictionary index is truncated; run `wortschatz update`")

    (offset,) = INDEX_OFFSET.unpack(packed_offset)
    with dictionary_path.open("rb") as dictionary:
        dictionary.seek(offset)
        line = dictionary.readline().decode("utf-8", errors="replace").strip()

    try:
        german, english = line.split("::", 1)
    except ValueError as error:
        raise WortschatzError("selected dictionary entry is malformed") from error

    return german.strip(), english.strip()


def format_entry(german: str, english: str, use_color: bool) -> str:
    if use_color:
        return f"\033[1;33m{german}\033[0m — {english}"
    return f"{german} — {english}"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="wortschatz",
        description="Print a random German-English dictionary entry.",
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
    subcommands = parser.add_subparsers(dest="command")
    update = subcommands.add_parser("update", help="download and index the dictionary")
    update.add_argument(
        "--url",
        default=DEFAULT_DICTIONARY_URL,
        help="ZIP archive containing de-en.txt",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = create_parser().parse_args(argv)
    data_dir = arguments.data_dir.expanduser()

    try:
        if arguments.command == "update":
            entry_count, download_size = update_dictionary(data_dir, arguments.url)
            size_mib = download_size / (1024 * 1024)
            print(f"Installed {entry_count:,} entries ({size_mib:.1f} MiB download).")
            return 0

        german, english = random_entry(data_dir)
        use_color = sys.stdout.isatty() and not arguments.plain and "NO_COLOR" not in os.environ
        print(format_entry(german, english, use_color))
        return 0
    except (OSError, WortschatzError) as error:
        print(f"wortschatz: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
