#!/bin/sh

set -eu

usage() {
    cat <<'EOF'
Usage: ./uninstall.sh [--shell bash|zsh|both|none] [--keep-data]

Removes the wortschatz executable and its managed shell startup hooks. Local
dictionary data is also removed unless --keep-data is specified.

Options:
  --shell MODE   Startup hooks to remove (default: both)
  --keep-data    Keep the downloaded dictionary and index
  -h, --help     Show this help
EOF
}

shell_mode=both
remove_data=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --shell)
            [ "$#" -ge 2 ] || { echo "uninstall.sh: --shell needs a value" >&2; exit 2; }
            shell_mode=$2
            shift 2
            ;;
        --keep-data)
            remove_data=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "uninstall.sh: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

case "$shell_mode" in
    bash|zsh|both|none) ;;
    *)
        echo "uninstall.sh: invalid shell mode: $shell_mode" >&2
        exit 2
        ;;
esac

install_home=${WORTSCHATZ_INSTALL_HOME:-"$HOME"}
bin_dir=$install_home/.local/bin
data_dir=${XDG_DATA_HOME:-"$install_home/.local/share"}/wortschatz
target=$bin_dir/wortschatz

if [ -f "$target" ]; then
    rm -f "$target"
    echo "Removed $target"
else
    echo "Executable not found at $target"
fi

remove_hook() {
    rc_file=$1
    start_marker='# >>> wortschatz-cli >>>'
    end_marker='# <<< wortschatz-cli <<<'

    if [ ! -f "$rc_file" ] || ! grep -Fq "$start_marker" "$rc_file"; then
        echo "Startup hook not found in $rc_file"
        return
    fi

    temporary_file=$(mktemp "${TMPDIR:-/tmp}/wortschatz-uninstall.XXXXXX")
    if ! awk -v start="$start_marker" -v end="$end_marker" '
        $0 == start { skipping = 1; found = 1; next }
        $0 == end && skipping { skipping = 0; next }
        !skipping { print }
        END { if (skipping || !found) exit 1 }
    ' "$rc_file" > "$temporary_file"; then
        rm -f "$temporary_file"
        echo "uninstall.sh: incomplete startup block in $rc_file; left it unchanged" >&2
        return 1
    fi
    cat "$temporary_file" > "$rc_file"
    rm -f "$temporary_file"
    echo "Removed startup hook from $rc_file"
}

case "$shell_mode" in
    bash)
        remove_hook "$install_home/.bashrc"
        ;;
    zsh)
        remove_hook "${ZDOTDIR:-$install_home}/.zshrc"
        ;;
    both)
        remove_hook "$install_home/.bashrc"
        remove_hook "${ZDOTDIR:-$install_home}/.zshrc"
        ;;
    none) ;;
esac

if [ "$remove_data" -eq 1 ]; then
    for filename in de-en.txt de-en.idx metadata.json; do
        if [ -f "$data_dir/$filename" ]; then
            rm -f "$data_dir/$filename"
            echo "Removed $data_dir/$filename"
        fi
    done

    if [ -d "$data_dir" ]; then
        if rmdir "$data_dir" 2>/dev/null; then
            echo "Removed empty directory $data_dir"
        else
            echo "Kept non-empty directory $data_dir"
        fi
    fi
else
    echo "Kept dictionary data in $data_dir"
fi

echo "Wortschatz CLI has been uninstalled."
