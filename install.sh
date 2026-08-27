#!/bin/sh

set -eu

usage() {
    cat <<'EOF'
Usage: ./install.sh [--shell auto|bash|zsh|both|none] [--skip-download]

Installs wortschatz to ~/.local/bin, downloads the dictionary, and adds an
idempotent startup hook to the selected shell configuration file.

Options:
  --shell MODE      Shell to configure (default: auto)
  --skip-download   Install the program without downloading dictionary data
  -h, --help        Show this help
EOF
}

shell_mode=auto
download_dictionary=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --shell)
            [ "$#" -ge 2 ] || { echo "install.sh: --shell needs a value" >&2; exit 2; }
            shell_mode=$2
            shift 2
            ;;
        --skip-download)
            download_dictionary=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "install.sh: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$shell_mode" in
    auto|bash|zsh|both|none) ;;
    *)
        echo "install.sh: invalid shell mode: $shell_mode" >&2
        exit 2
        ;;
esac

command -v python3 >/dev/null 2>&1 || {
    echo "install.sh: Python 3 is required" >&2
    exit 1
}

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_home=${WORTSCHATZ_INSTALL_HOME:-"$HOME"}
bin_dir=$install_home/.local/bin
data_dir=${XDG_DATA_HOME:-"$install_home/.local/share"}/wortschatz
target=$bin_dir/wortschatz

mkdir -p "$bin_dir"
cp "$script_dir/wortschatz.py" "$target"
chmod 0755 "$target"
echo "Installed $target"

if [ "$download_dictionary" -eq 1 ]; then
    python3 "$target" --data-dir "$data_dir" update
fi

if [ "$shell_mode" = auto ]; then
    case "${SHELL##*/}" in
        bash) shell_mode=bash ;;
        zsh) shell_mode=zsh ;;
        *)
            echo "install.sh: could not detect Bash or Zsh; skipping the startup hook" >&2
            shell_mode=none
            ;;
    esac
fi

add_hook() {
    rc_file=$1
    marker='# >>> wortschatz-cli >>>'

    if [ -f "$rc_file" ] && grep -Fq "$marker" "$rc_file"; then
        echo "Startup hook already present in $rc_file"
        return
    fi

    mkdir -p "$(dirname -- "$rc_file")"
    {
        printf '\n%s\n' "$marker"
        cat <<'EOF'
if [ -t 1 ] && [ -x "$HOME/.local/bin/wortschatz" ]; then
    "$HOME/.local/bin/wortschatz"
fi
# <<< wortschatz-cli <<<
EOF
    } >> "$rc_file"
    echo "Added startup hook to $rc_file"
}

case "$shell_mode" in
    bash)
        add_hook "$install_home/.bashrc"
        ;;
    zsh)
        add_hook "${ZDOTDIR:-$install_home}/.zshrc"
        ;;
    both)
        add_hook "$install_home/.bashrc"
        add_hook "${ZDOTDIR:-$install_home}/.zshrc"
        ;;
    none) ;;
esac

echo "Run '$target' to try it now."
