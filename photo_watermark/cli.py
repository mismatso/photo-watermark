"""With no arguments start GTK; `batch` performs the same work without a display."""

import argparse
from pathlib import Path
import sys

from .core import Logo, POSITIONS, Settings, WatermarkError, discover_images, process_batch


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Marcas de agua. Sin argumentos abre la aplicación de escritorio.")
    subparsers = parser.add_subparsers(dest="command")
    batch = subparsers.add_parser("batch", help="Procesar fotografías desde la terminal")
    batch.add_argument("photos", nargs="+", type=Path, help="Fotografías o carpetas")
    batch.add_argument("--logo", required=True, type=Path)
    batch.add_argument("--output", required=True, type=Path, help="Carpeta para las copias")
    batch.add_argument("--axis", choices=["width", "height"], default="width")
    batch.add_argument("--unit", choices=["px", "percent"], default="percent")
    batch.add_argument("--size", type=float, default=30)
    batch.add_argument("--position", choices=list(POSITIONS), default="bottom-right")
    batch.add_argument("--margin", type=int, default=100)
    batch.add_argument("--opacity", type=float, default=100)
    batch.add_argument("--format", choices=["original", "jpeg", "png", "webp", "tiff"], default="original")
    batch.add_argument("--recursive", action="store_true", help="Incluir subcarpetas de fotografías")
    args = parser.parse_args(argv)
    if args.command is None:
        try:
            from .gui import run
        except (ImportError, ValueError) as exc:
            print(f"No se puede iniciar la interfaz: {exc}\n"
                  "Instala: sudo apt install python3-gi gir1.2-gtk-3.0 python3-pil librsvg2-common", file=sys.stderr)
            return 1
        return run()
    try:
        settings = Settings(args.axis, args.unit, args.size, args.position, args.margin, args.opacity)
        settings.validate()
        logo = Logo(args.logo)
        photos = []
        output = args.output.expanduser().resolve()
        for path in args.photos:
            path = path.expanduser().resolve()
            if path.is_dir():
                # If output is the input folder itself, exclusive naming still protects files.
                photos.extend(discover_images(path, recursive=args.recursive,
                                              exclude=[output] if output != path else []))
            elif path.is_file():
                photos.append(path)
            else:
                raise WatermarkError(f"No existe: {path}")
        photos = list(dict.fromkeys(photos))
        if not photos:
            raise WatermarkError("No se encontraron fotografías compatibles.")
        failures = 0
        for result in process_batch(photos, logo, settings, output, args.format):
            if result.error:
                failures += 1
                print(f"ERROR: {result.source.name}: {result.error}", file=sys.stderr)
            else:
                print(result.destination)
        print(f"{len(photos) - failures} copias guardadas; {failures} errores.")
        return 1 if failures else 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Proceso interrumpido. Las copias ya terminadas se conservan.", file=sys.stderr)
        return 130
