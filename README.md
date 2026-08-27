# WORTSCHATZ-CLI

Build your Wortschatz, one terminal at a time.

`wortschatz` prints a random German dictionary entry with a translation whenever you open an interactive Bash or Zsh terminal. Spanish is the default target; English is also available. It is a dependency-free Python 3 program, and internet is only needed when installing or updating its local dictionary.

```text
die Lösung {f} — solution; answer; resolution
```

## Install

Configure the shell that launched the installer:

```sh
./install.sh
```

Or configure Bash and Zsh explicitly:

```sh
./install.sh --shell both
```

Install with German-to-English entries instead:

```sh
./install.sh --language en
```

The installer:

1. copies the program to `~/.local/bin/wortschatz`;
2. downloads the selected dictionary to `~/.local/share/wortschatz`;
3. builds a compact offset index for fast terminal startup; and
4. adds an idempotent managed block to `~/.bashrc`, `~/.zshrc`, or both.

The generated hook is valid in both shells:

```sh
# >>> wortschatz-cli >>>
if [ -t 1 ] && [ -x "$HOME/.local/bin/wortschatz" ]; then
    "$HOME/.local/bin/wortschatz" --language es
fi
# <<< wortschatz-cli <<<
```

The `-t` check prevents output in non-interactive sessions. Python can be executed from a shell startup file like any other executable; the script's `#!/usr/bin/env python3` shebang selects the interpreter.

## Usage

Print another entry:

```sh
wortschatz
```

Refresh the default German-to-Spanish dictionary and index:

```sh
wortschatz update
```

Download and print German-to-English entries:

```sh
wortschatz update --language en
wortschatz --language en
```

The English and Spanish dictionaries can be installed side by side. The `--language` option accepts `en` and `es` (and can also be written as `--to`).

Show the number of entries in an installed dictionary:

```sh
wortschatz stats
wortschatz stats --language en
```

Updates show a terminal download progress bar and report the installed entry count. Spanish source files are converted from their original Latin-1 encoding to UTF-8 when installed, so accented characters display correctly.

Disable color:

```sh
wortschatz --plain
```

To install the executable without downloading data or editing a startup file:

```sh
./install.sh --skip-download --shell none
```

## Uninstall

Remove the executable, downloaded dictionary, index, metadata, and the managed
startup blocks from both Bash and Zsh:

```sh
./uninstall.sh
```

The uninstaller removes only the known dictionary, index, and metadata files and the lines between the `wortschatz-cli` markers. It does not delete either shell configuration file or unrelated files in the data directory.

Keep the downloaded dictionary for a future reinstall:

```sh
./uninstall.sh --keep-data
```

Remove a hook from only one shell with `--shell bash` or `--shell zsh`.

## Dictionary source and license

The English option downloads the German-English DING/BEOLINGUS dictionary from [Technische Universität Chemnitz](https://www-user.tu-chemnitz.de/~fri/ding/).
The Spanish option downloads a [SourceForge mirror of the Spanish-German DING list](https://sourceforge.net/projects/macding/files/german-spanish%20dictionary/) associated with the [Savannah ding-es-de project](https://savannah.nongnu.org/projects/ding-es-de/) and normalizes its Spanish-first entries to the German-first format used by this CLI.

The downloaded dictionaries are not included in this repository and retain their own licenses after download. The English list is licensed under GPL-2.0-or-later. The Spanish list is distributed under GPL-2.0-or-later, GFDL-1.2-or-later, and CC BY-SA 1.0. The `wortschatz-cli` source code is licensed separately under the repository's MIT license.

## Development

Run the standard-library test suite:

```sh
python3 -m unittest discover -s tests -v
```
