#!/usr/bin/python3
"""Entry point that also works when launched outside the project directory."""

import sys

if __name__ == "__main__":
    try:
        from photo_watermark.cli import main
    except ImportError as exc:
        print(f"Falta una dependencia: {exc}\n"
              "Instala: sudo apt install python3-gi gir1.2-gtk-3.0 python3-pil librsvg2-common",
              file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main())
