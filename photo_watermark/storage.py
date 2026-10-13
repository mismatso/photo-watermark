"""Small XDG-compliant, per-user logo library and persistent presets."""

from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import tempfile

from .core import Logo, Settings, WatermarkError


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Store:
    def __init__(self, config_dir: Path | None = None, data_dir: Path | None = None):
        self.config_dir = config_dir or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "photo-watermark"
        self.data_dir = data_dir or Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "photo-watermark"
        self.path = self.config_dir / "settings.json"
        self.logo_dir = self.data_dir / "logos"
        self.warning = ""
        self.state = {"version": 1, "folders": [], "presets": {}, "last": {}}
        if self.path.exists():
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(state, dict) or state.get("version") != 1:
                    raise ValueError("versión de configuración desconocida")
                if not isinstance(state.get("folders"), list) or not all(isinstance(p, str) for p in state["folders"]):
                    raise ValueError("lista de carpetas no válida")
                if not isinstance(state.get("presets"), dict) or not isinstance(state.get("last"), dict):
                    raise ValueError("configuraciones no válidas")
                if not all(isinstance(value, dict) for value in state["presets"].values()):
                    raise ValueError("configuraciones guardadas no válidas")
                self.state = state
            except (OSError, ValueError) as exc:
                self.warning = f"No se pudo cargar la configuración: {exc}. Se usan valores iniciales."

    @property
    def folders(self) -> list[Path]:
        return list(dict.fromkeys([PROJECT_ROOT / "logos", self.logo_dir] +
                                 [Path(p).expanduser() for p in self.state["folders"]]))

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=self.config_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.state, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def add_folder(self, folder: Path) -> None:
        value = str(folder.expanduser().resolve())
        if value not in self.state["folders"]:
            self.state["folders"].append(value)
        self.save()

    def import_logo(self, source: Path) -> Path:
        source = source.expanduser().resolve()
        Logo(source)  # Validate before adding a file to the persistent library.
        self.logo_dir.mkdir(parents=True, exist_ok=True)
        if source.parent == self.logo_dir.resolve():
            return source
        for number in range(1, 1_000_001):
            extra = "" if number == 1 else f"_{number}"
            destination = self.logo_dir / f"{source.stem}{extra}{source.suffix.lower()}"
            try:
                stream = destination.open("xb")
            except FileExistsError:
                continue
            try:
                with source.open("rb") as original, stream:
                    shutil.copyfileobj(original, stream)
            except BaseException:
                destination.unlink(missing_ok=True)
                raise
            return destination
        raise WatermarkError("No se pudo asignar un nombre al logo.")

    def snapshot(self, logo: Path | None, settings: Settings, output_format: str) -> dict:
        return {"logo": str(logo) if logo else "", "settings": asdict(settings),
                "format": output_format}
