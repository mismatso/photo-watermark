#!/bin/sh
# Use Debian's Python, which can see the GTK and Pillow packages installed by apt.
program_dir=$(dirname -- "$(readlink -f -- "$0")")
exec /usr/bin/python3 "$program_dir/app.py" "$@"
