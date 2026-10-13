"""Image processing shared by the GTK interface and the command-line interface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import threading
from typing import Iterable, Iterator

from PIL import Image, ImageOps


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
LOGO_EXTENSIONS = PHOTO_EXTENSIONS | {".svg"}
POSITIONS = {
    "top-left": ("Superior izquierda", "left", "top"),
    "top-center": ("Superior centro", "center", "top"),
    "top-right": ("Superior derecha", "right", "top"),
    "center-left": ("Centro izquierda", "left", "center"),
    "center-right": ("Centro derecha", "right", "center"),
    "bottom-left": ("Inferior izquierda", "left", "bottom"),
    "bottom-center": ("Inferior centro", "center", "bottom"),
    "bottom-right": ("Inferior derecha", "right", "bottom"),
}


class WatermarkError(ValueError):
    """A recoverable input or sizing error, suitable for displaying to the user."""


@dataclass(frozen=True)
class Settings:
    axis: str = "width"
    unit: str = "percent"
    size: float = 30
    position: str = "bottom-right"
    margin: int = 100
    opacity: float = 100

    def validate(self) -> None:
        if self.axis not in {"width", "height"}:
            raise WatermarkError("La dimensión debe ser ancho o alto.")
        if self.unit not in {"px", "percent"}:
            raise WatermarkError("La unidad debe ser píxeles o porcentaje.")
        if not math.isfinite(self.size) or self.size <= 0:
            raise WatermarkError("El tamaño debe ser mayor que cero.")
        if self.unit == "percent" and self.size > 100:
            raise WatermarkError("El porcentaje debe estar entre 0 y 100.")
        if self.unit == "px" and not float(self.size).is_integer():
            raise WatermarkError("El tamaño en píxeles debe ser un número entero.")
        if self.position not in POSITIONS:
            raise WatermarkError("Selecciona una de las ocho posiciones.")
        if type(self.margin) is not int or self.margin < 0:
            raise WatermarkError("El margen debe ser un número entero de píxeles, desde cero.")
        if not math.isfinite(self.opacity) or not 0 <= self.opacity <= 100:
            raise WatermarkError("La opacidad debe estar entre 0 y 100.")


@dataclass(frozen=True)
class Placement:
    width: int
    height: int
    x: int
    y: int


def _rounded(value: float) -> int:
    return max(1, math.floor(value + 0.5))


def calculate_placement(
    photo_size: tuple[int, int], logo_size: tuple[int, int], settings: Settings
) -> Placement:
    """Calculate in original, EXIF-oriented photo pixels, never preview pixels."""
    settings.validate()
    pw, ph = photo_size
    lw, lh = logo_size
    if min(pw, ph, lw, lh) <= 0:
        raise WatermarkError("La fotografía y el logo deben tener dimensiones válidas.")
    index = 0 if settings.axis == "width" else 1
    target = settings.size
    if settings.unit == "percent":
        target *= photo_size[index] / 100
    target = _rounded(target)
    if settings.axis == "width":
        width, height = target, _rounded(target * lh / lw)
    else:
        width, height = _rounded(target * lw / lh), target

    _, horizontal, vertical = POSITIONS[settings.position]
    x = {"left": settings.margin, "center": (pw - width) // 2,
         "right": pw - width - settings.margin}[horizontal]
    y = {"top": settings.margin, "center": (ph - height) // 2,
         "bottom": ph - height - settings.margin}[vertical]
    # Only anchored edges use the margin. The opposite edges just have to fit.
    if x < 0 or y < 0 or x + width > pw or y + height > ph:
        raise WatermarkError(
            f"La marca de {width} × {height} px con margen de {settings.margin} px "
            f"no cabe en la fotografía de {pw} × {ph} px. Reduce el tamaño o el margen."
        )
    return Placement(width, height, x, y)


def _pixbuf_module():
    try:
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        return GdkPixbuf
    except (ImportError, ValueError) as exc:
        raise WatermarkError(
            "Para usar SVG instala python3-gi y librsvg2-common."
        ) from exc


class Logo:
    """Keep a raster original; render SVG directly at the requested final size."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self._image = None
        self._cached_size = None
        self._cached_render = None
        if self.path.suffix.lower() not in LOGO_EXTENSIONS:
            raise WatermarkError("Usa un logo PNG, SVG, JPEG, WebP o TIFF.")
        if self.path.suffix.lower() == ".svg":
            pixbuf = _pixbuf_module()
            info, width, height = pixbuf.Pixbuf.get_file_info(str(self.path))
            if info is None or min(width, height) <= 0:
                raise WatermarkError("No se puede leer el SVG. Revisa el archivo y librsvg2-common.")
            self.size = (width, height)
        else:
            with Image.open(self.path) as image:
                self._image = ImageOps.exif_transpose(image).convert("RGBA")
            self.size = self._image.size

    def render(self, size: tuple[int, int]) -> Image.Image:
        if self._cached_size == size:
            return self._cached_render.copy()
        if self._image is not None:
            image = self._image.resize(size, Image.Resampling.LANCZOS)
        else:
            pixbuf = _pixbuf_module().Pixbuf.new_from_file_at_scale(
                str(self.path), size[0], size[1], False
            )
            mode = "RGBA" if pixbuf.get_has_alpha() else "RGB"
            image = Image.frombytes(
                mode, (pixbuf.get_width(), pixbuf.get_height()), pixbuf.get_pixels(),
                "raw", mode, pixbuf.get_rowstride(), 1,
            ).convert("RGBA")
        self._cached_size, self._cached_render = size, image
        return image.copy()


def load_photo(path: Path | str) -> Image.Image:
    with Image.open(path) as image:
        if getattr(image, "n_frames", 1) > 1:
            raise WatermarkError("Solo se admiten fotografías estáticas; el archivo tiene varias páginas o cuadros.")
        oriented = ImageOps.exif_transpose(image)
        result = oriented.convert("RGBA")
        result.info = oriented.info.copy()
        # A CMYK profile cannot describe the RGB pixels produced by conversion.
        if oriented.mode == "CMYK":
            result.info.pop("icc_profile", None)
        return result


def _apply_opacity(image: Image.Image, opacity: float) -> Image.Image:
    if opacity != 100:
        image.putalpha(image.getchannel("A").point(
            [round(value * opacity / 100) for value in range(256)]
        ))
    return image


def stamp(photo: Image.Image, logo: Logo, settings: Settings) -> tuple[Image.Image, Placement]:
    placement = calculate_placement(photo.size, logo.size, settings)
    overlay = _apply_opacity(logo.render((placement.width, placement.height)), settings.opacity)
    result = photo.convert("RGBA")
    result.alpha_composite(overlay, (placement.x, placement.y))
    result.info = photo.info.copy()
    return result, placement


def preview(
    photo: Image.Image, logo: Logo, settings: Settings, bounds: tuple[int, int]
) -> tuple[Image.Image, Placement]:
    placement = calculate_placement(photo.size, logo.size, settings)
    result = photo.convert("RGBA")
    result.thumbnail(bounds, Image.Resampling.LANCZOS)
    sx, sy = result.width / photo.width, result.height / photo.height
    overlay = logo.render((_rounded(placement.width * sx), _rounded(placement.height * sy)))
    result.alpha_composite(_apply_opacity(overlay, settings.opacity),
                           (round(placement.x * sx), round(placement.y * sy)))
    return result, placement


def discover_images(folder: Path | str, *, logos: bool = False, recursive: bool = True,
                    exclude: Iterable[Path] = ()) -> list[Path]:
    folder = Path(folder).expanduser().resolve()
    extensions = LOGO_EXTENSIONS if logos else PHOTO_EXTENSIONS
    excluded = [Path(path).expanduser().resolve() for path in exclude]
    entries = folder.rglob("*") if recursive else folder.iterdir()
    return sorted({p.resolve() for p in entries if p.is_file() and
                   p.suffix.lower() in extensions and
                   not any(p.resolve().is_relative_to(root) for root in excluded)},
                  key=lambda p: str(p).casefold())


def save_copy(image: Image.Image, source: Path, output_dir: Path,
              output_format: str = "original") -> Path:
    formats = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG",
               ".webp": "WEBP", ".tif": "TIFF", ".tiff": "TIFF"}
    if output_format == "original":
        suffix = source.suffix.lower()
    else:
        suffix = {"jpeg": ".jpg", "png": ".png", "webp": ".webp", "tiff": ".tiff"}.get(output_format)
    if suffix not in formats:
        raise WatermarkError("El formato de salida no es válido.")
    output_dir = Path(output_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    file_format = formats[suffix]
    options = {key: image.info[key] for key in ("exif", "icc_profile", "dpi") if image.info.get(key)}
    output = image
    if file_format == "JPEG":
        output = Image.new("RGB", image.size, "white")
        output.paste(image, mask=image.getchannel("A"))
        options.update(quality=95, subsampling=0)
    elif file_format == "WEBP":
        options.pop("dpi", None)
        options.update(quality=95, method=6)
    elif file_format == "TIFF":
        options.update(compression="tiff_lzw")
    for number in range(1, 1_000_001):
        extra = "" if number == 1 else f"_{number}"
        destination = output_dir / f"{source.stem}_marca{extra}{suffix}"
        try:
            # Exclusive creation protects existing originals, exports and symlinks.
            stream = destination.open("xb")
        except FileExistsError:
            continue
        try:
            with stream:
                output.save(stream, format=file_format, **options)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return destination
    raise WatermarkError("No se pudo encontrar un nombre disponible para la copia.")


@dataclass(frozen=True)
class BatchResult:
    source: Path
    destination: Path | None = None
    error: str | None = None


def process_batch(sources: Iterable[Path], logo: Logo, settings: Settings,
                  output_dir: Path, output_format: str = "original",
                  cancel: threading.Event | None = None) -> Iterator[BatchResult]:
    settings.validate()
    for source in sources:
        if cancel is not None and cancel.is_set():
            break
        try:
            photo = load_photo(source)
            marked, _ = stamp(photo, logo, settings)
            destination = save_copy(marked, source, output_dir, output_format)
            yield BatchResult(source, destination)
        except Exception as exc:
            # A bad photo does not abort the remaining photos in a batch.
            yield BatchResult(source, error=str(exc))
