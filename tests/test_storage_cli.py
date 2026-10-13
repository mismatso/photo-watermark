from contextlib import redirect_stdout, redirect_stderr
from dataclasses import asdict
import io
import json
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from photo_watermark.cli import main
from photo_watermark.core import Settings
from photo_watermark.storage import Store


class StorageAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "config", self.root / "data")
        self.logo = self.root / "marca con ñ.png"
        Image.new("RGBA", (20, 10), "red").save(self.logo)
        self.photo = self.root / "fotografía.JPG"
        Image.new("RGB", (200, 100), "blue").save(self.photo)

    def tearDown(self):
        self.temp.cleanup()

    def test_named_presets_and_last_settings_survive_restart(self):
        settings = Settings(axis="height", unit="px", size=750, position="top-left", margin=100)
        saved = self.store.snapshot(self.logo, settings, "png")
        self.store.state["presets"]["Panadería"] = saved
        self.store.state["last"] = saved
        self.store.save()
        restored = Store(self.store.config_dir, self.store.data_dir)
        self.assertEqual(restored.state["last"]["settings"], asdict(settings))
        self.assertEqual(restored.state["presets"]["Panadería"], saved)
        self.assertFalse(list(self.store.config_dir.glob(".settings-*")))

    def test_imported_logo_is_independent_and_preserves_collision(self):
        imported = self.store.import_logo(self.logo)
        again = self.store.import_logo(self.logo)
        self.assertNotEqual(imported, again)
        self.assertEqual(imported.read_bytes(), self.logo.read_bytes())
        self.assertEqual(self.store.import_logo(imported), imported)

    def test_custom_logo_folders_persist_without_duplicates(self):
        self.store.add_folder(self.root)
        self.store.add_folder(self.root)
        restored = Store(self.store.config_dir, self.store.data_dir)
        self.assertEqual(restored.state["folders"], [str(self.root)])
        self.assertIn(self.root, restored.folders)

    def test_invalid_config_uses_defaults_with_warning(self):
        self.store.config_dir.mkdir()
        for invalid in ('broken', '[]', '{"version":100}',
                        '{"version":1,"folders":[123],"presets":{},"last":{}}'):
            with self.subTest(invalid=invalid):
                self.store.path.write_text(invalid)
                restored = Store(self.store.config_dir, self.store.data_dir)
                self.assertTrue(restored.warning)
                self.assertEqual(restored.state["presets"], {})

    def test_cli_fixed_pixels_and_unicode_paths(self):
        out = self.root / "salida de prueba"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["batch", str(self.photo), "--logo", str(self.logo),
                         "--output", str(out), "--unit", "px", "--size", "20", "--margin", "5"])
        self.assertEqual(code, 0)
        self.assertTrue((out / "fotografía_marca.jpg").exists())

    def test_cli_reports_invalid_settings_without_creating_output(self):
        out = self.root / "out"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["batch", str(self.photo), "--logo", str(self.logo),
                         "--output", str(out), "--size", "150"])
        self.assertEqual(code, 1)
        self.assertFalse(out.exists())

    def test_cli_partial_failure_returns_nonzero_and_continues(self):
        bad = self.root / "broken.jpg"
        bad.write_bytes(b"bad")
        out = self.root / "out"
        error = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(error):
            code = main(["batch", str(bad), str(self.photo), "--logo", str(self.logo),
                         "--output", str(out), "--size", "10", "--margin", "0"])
        self.assertEqual(code, 1)
        self.assertIn("broken.jpg", error.getvalue())
        self.assertTrue((out / "fotografía_marca.jpg").exists())

    def test_cli_directory_excludes_output_subdirectory(self):
        out = self.root / "out"
        out.mkdir()
        Image.new("RGB", (100, 100), "green").save(out / "old.png")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["batch", str(self.root), "--recursive", "--logo", str(self.logo),
                         "--output", str(out), "--unit", "px", "--size", "5", "--margin", "0"])
        self.assertEqual(code, 0)
        self.assertFalse((out / "old_marca.png").exists())
        self.assertEqual(len(list(out.iterdir())), 3)
