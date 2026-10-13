#!/usr/bin/python3
"""Install a Cinnamon menu entry for this checkout (no root access required)."""

import argparse
import os
from pathlib import Path

from photo_watermark import APP_NAME


def desktop_quote(value: str) -> str:
    # Exec uses desktop-entry quoting, rather than shell quoting.
    value = value.replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value + '"'


def main():
    parser = argparse.ArgumentParser(description=f"Añadir {APP_NAME} al menú de aplicaciones de Cinnamon.")
    parser.add_argument("--directory", type=Path, help="Carpeta alternativa para guardar el lanzador")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    folder = args.directory or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "com.photo_watermark.Desktop.desktop"
    executable = desktop_quote(str(root / "app.py"))
    target.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "Comment=Aplicar logos a una fotografía o un lote\n"
        f"Exec=/usr/bin/python3 {executable}\n"
        f"Icon={root / 'assets/photo-watermark.svg'}\n"
        "Terminal=false\n"
        "Categories=Graphics;Photography;\n"
        "Keywords=foto;logo;marca;agua;watermark;\n"
        "StartupNotify=true\n",
        encoding="utf-8",
    )
    print(f"Lanzador creado: {target}")
    print(f"Busca «{APP_NAME}» en el menú de Cinnamon. Si mueves el proyecto, vuelve a ejecutar este instalador.")


if __name__ == "__main__":
    main()
