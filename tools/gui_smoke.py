#!/usr/bin/python3
"""Exercise GTK controls and background export, with isolated user data."""

import argparse
from dataclasses import asdict
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Gio
from PIL import Image

from photo_watermark import (APP_NAME, APP_DESCRIPTION, AUTHOR, COPYRIGHT,
                             WEBSITE, WEBSITE_LABEL, __version__)
from photo_watermark.core import Settings
from photo_watermark.gui import LogoDialog, Window
from photo_watermark.storage import Store


def pump_until(condition, timeout=20):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("La interfaz no terminó la operación dentro del tiempo esperado.")


def capture_window(window, path):
    # A mapped window may still be blank until its first painted frame.
    painted = []
    clock = window.get_frame_clock()
    handler = clock.connect("after-paint", lambda *_: painted.append(True))
    window.queue_draw()
    pump_until(lambda: bool(painted))
    clock.disconnect(handler)
    window.get_display().sync()
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0,
                                      window.get_allocated_width(), window.get_allocated_height())
    image.savev(str(path), "png", [], [])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--about-screenshot", type=Path)
    args = parser.parse_args()
    success, _ = Gtk.init_check(None)
    if not success:
        print("No hay una sesión gráfica disponible.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="photo-watermark-gui-") as temporary:
        root = Path(temporary)
        store = Store(root / "config", root / "data")
        app = Gtk.Application(application_id="com.photo_watermark.Smoke",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
        app.register(None)
        window = Window(app, store)
        try:
            window.resize(1100, 650)
            pump_until(lambda: window.get_size()[1] <= 650 and window.get_size()[0] >= 1000)
            assert window.export_button.get_allocation().height > 0
            window.menu_button.set_active(True)
            pump_until(lambda: window.application_menu.get_mapped())
            window.application_menu.popdown()
            window.menu_button.set_active(False)
            window.about_item.activate()
            pump_until(lambda: window.about_dialog is not None and window.about_dialog.get_mapped())
            about = window.about_dialog
            assert about.get_title() == f"Acerca de {APP_NAME}"
            assert about.get_program_name() == APP_NAME
            assert about.get_version() == __version__ == "1.0"
            assert about.get_comments() == APP_DESCRIPTION
            assert about.get_copyright() == COPYRIGHT
            assert about.get_website() == WEBSITE
            assert about.get_website_label() == WEBSITE_LABEL
            assert about.get_authors() == [AUTHOR]
            assert about.get_license_type() == Gtk.License.GPL_3_0
            if args.about_screenshot:
                capture_window(about, args.about_screenshot)
                print(f"Acerca de: {args.about_screenshot}")
            about.response(Gtk.ResponseType.CANCEL)
            pump_until(lambda: not about.get_visible())
            window.about_item.activate()
            assert window.about_dialog is about
            about.close()
            pump_until(lambda: not about.get_visible())
            photograph = next((ROOT / "fotos").rglob("*.jpg"), None)
            if photograph is None:
                photograph = root / "photo.jpg"
                Image.new("RGB", (2400, 1600), "#789ba8").save(photograph)
            window.add_photos([photograph])
            pump_until(lambda: window.preview_info.get_text().startswith("Foto:"))
            assert len(window.position_buttons) == 8
            for key, toggle in window.position_buttons.items():
                toggle.set_active(True)
                assert window.position == key
                assert sum(button.get_active() for button in window.position_buttons.values()) == 1

            gallery = LogoDialog(window, window.logo_paths, window.logo_path)
            assert gallery.selected() == window.logo_path
            gallery.search.set_text("isologo")
            gallery.filtered.refilter()
            assert len(gallery.filtered) > 0
            gallery.destroy()

            settings = Settings(axis="height", unit="px", size=750,
                                position="top-center", margin=100)
            state = store.snapshot(window.logo_path, settings, "png")
            store.state["presets"]["Prueba de configuración"] = state
            window._refresh_presets()
            window.presets.set_active_id("preset:Prueba de configuración")
            assert window._settings() == settings
            pump_until(lambda: window.preview_info.get_text().startswith("Foto:") and
                       "750 px" in window.preview_info.get_text())

            # Restore defaults and test one bad file in a batch.
            window._restore(store.snapshot(window.logo_path, Settings(), "original"))
            window.presets.set_active_id("current")
            bad = root / "broken.jpg"
            bad.write_bytes(b"not a photograph")
            window.add_photos([bad])
            window.output.set_text(str(root / "exports"))
            original_bytes = photograph.read_bytes()
            window._export()
            assert window.busy
            pump_until(lambda: not window.busy)
            assert len(window.batch_results) == 2
            assert window.batch_results[0].destination.is_file()
            assert window.batch_results[1].error
            assert photograph.read_bytes() == original_bytes
            assert window.settings_box.get_sensitive()
            assert "1 errores" in window.progress.get_text()

            # Remove the bad fixture from the screenshot and show the real photograph.
            window.photos.remove(window.photos.get_iter(1))
            window._refresh_count()
            window.notice.hide()
            window.progress.set_text("Prueba completada · 1 copia guardada")
            window.output.set_text(str(ROOT / "resultados"))
            window.photo_tree.get_selection().select_path(0)
            window._changed()
            pump_until(lambda: window.preview_info.get_text().startswith("Foto:"))
            if args.screenshot:
                pump_until(lambda: window.get_window() is not None)
                capture_window(window, args.screenshot)
                print(f"Captura: {args.screenshot}")
            window._persist()
            restored = Store(store.config_dir, store.data_dir)
            assert restored.state["last"]["settings"] == asdict(Settings())
            print(f"GTK: ocho posiciones, galería de {len(window.logo_paths)} logos, configuraciones, "
                  "vista previa, exportación, menú y diálogo Acerca de verificados. Contenido usable a 1100 × 650.")
        finally:
            window._close()
            window.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
