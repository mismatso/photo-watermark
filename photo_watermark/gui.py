"""Native GTK 3 desktop interface. Workers never read or modify GTK widgets."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango
from PIL import Image, ImageDraw

from . import (APP_NAME, APP_DESCRIPTION, AUTHOR, COPYRIGHT,
               WEBSITE, WEBSITE_LABEL, __version__)
from .core import (LOGO_EXTENSIONS, PHOTO_EXTENSIONS, POSITIONS, Logo, Settings,
                   WatermarkError, discover_images, load_photo, preview, process_batch)
from .storage import PROJECT_ROOT, Store


OUTPUT_FORMATS = {"original": "Conservar formato original", "jpeg": "JPEG · calidad 95",
                  "png": "PNG · sin pérdida", "webp": "WebP · calidad 95",
                  "tiff": "TIFF · sin pérdida"}


def pixbuf_from_image(image: Image.Image) -> GdkPixbuf.Pixbuf:
    image = image.convert("RGBA")
    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(image.tobytes()), GdkPixbuf.Colorspace.RGB,
        True, 8, image.width, image.height, image.width * 4,
    )


def logo_thumbnail(path: Path, bounds: tuple[int, int] = (220, 100)) -> Image.Image:
    logo = Logo(path)
    scale = min(bounds[0] / logo.size[0], bounds[1] / logo.size[1])
    size = tuple(max(1, round(side * scale)) for side in logo.size)
    image = Image.new("RGBA", bounds, "#dededb")
    draw = ImageDraw.Draw(image)
    for y in range(0, bounds[1], 10):
        for x in range(0, bounds[0], 10):
            if (x // 10 + y // 10) % 2 == 0:
                draw.rectangle((x, y, x + 9, y + 9), fill="#f6f6f2")
    image.alpha_composite(logo.render(size), ((bounds[0] - size[0]) // 2,
                                            (bounds[1] - size[1]) // 2))
    return image


def label(text: str, *, dim: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=0)
    widget.set_line_wrap(True)
    if dim:
        widget.get_style_context().add_class("dim-label")
    return widget


def section(text: str) -> Gtk.Label:
    widget = label(text)
    widget.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>")
    widget.set_margin_top(10)
    return widget


def combo(items: dict[str, str], selected: str) -> Gtk.ComboBoxText:
    widget = Gtk.ComboBoxText()
    for key, text in items.items():
        widget.append(key, text)
    widget.set_active_id(selected)
    return widget


def button(text: str, callback, *, suggested: bool = False) -> Gtk.Button:
    widget = Gtk.Button(label=text)
    widget.connect("clicked", callback)
    if suggested:
        widget.get_style_context().add_class("suggested-action")
    return widget


class LogoDialog(Gtk.Dialog):
    def __init__(self, parent, paths: list[Path], current: Path | None):
        super().__init__(title="Elegir marca de agua", transient_for=parent, modal=True)
        self.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Usar logo", Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        self.set_default_size(900, 520)
        content = self.get_content_area()
        content.set_spacing(10)
        content.set_border_width(16)
        self.search = Gtk.SearchEntry(placeholder_text="Buscar por nombre, carpeta o formato…")
        content.pack_start(self.search, False, False, 0)
        self.model = Gtk.ListStore(str, str, str)
        for path in paths:
            self.model.append((str(path), path.name, str(path.parent)))
        self.filtered = self.model.filter_new()
        self.filtered.set_visible_func(
            lambda model, tree_iter, _: self.search.get_text().casefold() in
            " ".join(model[tree_iter]).casefold()
        )
        self.search.connect("search-changed", lambda _: self.filtered.refilter())
        self.tree = Gtk.TreeView(model=self.filtered)
        self.tree.set_search_column(1)
        for title, column in (("Logo", 1), ("Carpeta", 2)):
            renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
            view_column = Gtk.TreeViewColumn(title, renderer, text=column)
            view_column.set_expand(True)
            view_column.set_resizable(True)
            self.tree.append_column(view_column)
        self.tree.connect("row-activated", lambda *_: self.response(Gtk.ResponseType.OK))
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.tree)
        content.pack_start(scroll, True, True, 0)
        self.image = Gtk.Image()
        self.description = label("Selecciona un logo para ver su vista previa.", dim=True)
        content.pack_start(self.image, False, False, 0)
        content.pack_start(self.description, False, False, 0)
        self.tree.get_selection().connect("changed", self._selection_changed)
        self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)
        if current is not None:
            for row in self.filtered:
                if row[0] == str(current):
                    self.tree.get_selection().select_path(row.path)
                    self.tree.scroll_to_cell(row.path, None, True, 0.5, 0)
                    break
        self.show_all()

    def _selection_changed(self, selection):
        model, tree_iter = selection.get_selected()
        valid = tree_iter is not None
        self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(valid)
        if not valid:
            return
        path = Path(model[tree_iter][0])
        try:
            self.image.set_from_pixbuf(pixbuf_from_image(logo_thumbnail(path, (360, 100))))
            self.description.set_text(str(path))
        except Exception as exc:
            self.image.clear()
            self.description.set_text(f"No se puede leer este logo: {exc}")
            self.get_widget_for_response(Gtk.ResponseType.OK).set_sensitive(False)

    def selected(self) -> Path | None:
        model, tree_iter = self.tree.get_selection().get_selected()
        return Path(model[tree_iter][0]) if tree_iter is not None else None


class Window(Gtk.ApplicationWindow):
    def __init__(self, application, store: Store):
        super().__init__(application=application, title=APP_NAME)
        self.store = store
        monitor = self.get_display().get_primary_monitor() or self.get_display().get_monitor(0)
        workarea = monitor.get_workarea() if monitor else None
        self.set_default_size(min(1180, workarea.width - 80) if workarea else 1180,
                              min(820, workarea.height - 120) if workarea else 820)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_from_file(str(PROJECT_ROOT / "assets/photo-watermark.svg"))
        self._ready = False
        self._applying = False
        self._closing = False
        self._preview_timer = 0
        self._save_timer = 0
        self._preview_generation = 0
        self._preview_future = None
        self._photo_cache = None
        self._photo_cache_path = None
        self._logo_cache = None
        self._logo_cache_path = None
        self.preview_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="preview")
        self.batch_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="export")
        self.cancel_event = threading.Event()
        self.busy = False
        self.logo_path = None
        self.logo_paths = []
        self.batch_results = []
        self.last_output_dir = None
        self.about_dialog = None
        self.position = "bottom-right"
        self._build()
        self._reload_logos()
        self._refresh_presets()
        self._restore(self.store.state.get("last", {}))
        self._ready = True
        self.connect("delete-event", self._close)
        self.show_all()
        self.cancel_button.hide()
        if not self.notice_label.get_text():
            self.notice.hide()
        self.report_button.hide()
        self.open_output_button.hide()
        self._refresh_count()
        self._changed()
        if self.store.warning:
            self._notify(self.store.warning, Gtk.MessageType.WARNING)

    def _build(self):
        header = Gtk.HeaderBar(title=APP_NAME, subtitle="Tu logo, en cada fotografía")
        header.set_show_close_button(True)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_image(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        self.menu_button.set_tooltip_text("Menú de la aplicación")
        self.menu_button.get_accessible().set_name("Menú de la aplicación")
        self.application_menu = Gtk.Menu()
        self.about_item = Gtk.MenuItem.new_with_mnemonic(f"_Acerca de {APP_NAME}")
        self.about_item.connect("activate", self._show_about)
        self.application_menu.append(self.about_item)
        self.application_menu.append(Gtk.SeparatorMenuItem())
        quit_item = Gtk.MenuItem.new_with_mnemonic("_Salir")
        quit_item.connect("activate", lambda _: self.close())
        self.application_menu.append(quit_item)
        self.application_menu.show_all()
        self.menu_button.set_popup(self.application_menu)
        header.pack_end(self.menu_button)
        self.set_titlebar(header)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add(root)
        self.notice = Gtk.InfoBar(show_close_button=True)
        self.notice.connect("response", lambda *_: self.notice.hide())
        self.notice_label = label("")
        self.notice.get_content_area().add(self.notice_label)
        root.pack_start(self.notice, False, False, 0)
        body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        body.set_position(345)
        root.pack_start(body, True, True, 0)

        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.settings_box.set_border_width(18)
        self.settings_box.set_size_request(305, -1)
        sidebar_scroll = Gtk.ScrolledWindow()
        sidebar_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar_scroll.add(self.settings_box)
        body.pack1(sidebar_scroll, resize=False, shrink=False)
        side = self.settings_box
        side.pack_start(section("Configuraciones guardadas"), False, False, 0)
        self.presets = Gtk.ComboBoxText()
        self.presets.connect("changed", self._preset_selected)
        side.pack_start(self.presets, False, False, 0)
        preset_actions = Gtk.Box(spacing=8)
        preset_actions.pack_start(button("Guardar…", self._save_preset), True, True, 0)
        preset_actions.pack_start(button("Eliminar", self._delete_preset), False, False, 0)
        side.pack_start(preset_actions, False, False, 0)

        side.pack_start(section("1. Logo"), False, False, 0)
        self.logo_image = Gtk.Image()
        side.pack_start(self.logo_image, False, False, 0)
        self.logo_label = Gtk.Label(xalign=0)
        self.logo_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.logo_label.set_max_width_chars(32)
        side.pack_start(self.logo_label, False, False, 0)
        self.choose_logo_button = button("Elegir logo…", self._choose_logo)
        side.pack_start(self.choose_logo_button, False, False, 0)
        logo_actions = Gtk.Box(spacing=8)
        logo_actions.pack_start(button("Importar logo…", self._import_logo), True, True, 0)
        logo_actions.pack_start(button("Añadir carpeta…", self._add_logo_folder), True, True, 0)
        side.pack_start(logo_actions, False, False, 0)
        self.logo_count = label("", dim=True)
        side.pack_start(self.logo_count, False, False, 0)

        side.pack_start(section("2. Tamaño proporcional"), False, False, 0)
        self.axis = combo({"width": "Ancho", "height": "Alto"}, "width")
        self.unit = combo({"percent": "Porcentaje de la fotografía", "px": "Píxeles fijos"}, "percent")
        side.pack_start(self.axis, False, False, 0)
        side.pack_start(self.unit, False, False, 0)
        self.size = Gtk.SpinButton.new_with_range(0.1, 100, 0.1)
        self.size.set_digits(1)
        self.size.set_value(30)
        size_line = Gtk.Box(spacing=8)
        size_line.pack_start(self.size, True, True, 0)
        self.size_suffix = label("%")
        size_line.pack_start(self.size_suffix, False, False, 0)
        side.pack_start(size_line, False, False, 0)
        self.size_hint = label("", dim=True)
        side.pack_start(self.size_hint, False, False, 0)

        side.pack_start(section("3. Posición y margen"), False, False, 0)
        grid = Gtk.Grid(column_spacing=6, row_spacing=6, column_homogeneous=True)
        self.position_buttons = {}
        for key, text, col, row in (
            ("top-left", "↖", 0, 0), ("top-center", "↑", 1, 0), ("top-right", "↗", 2, 0),
            ("center-left", "←", 0, 1), ("center-right", "→", 2, 1),
            ("bottom-left", "↙", 0, 2), ("bottom-center", "↓", 1, 2), ("bottom-right", "↘", 2, 2),
        ):
            toggle = Gtk.ToggleButton(label=text)
            toggle.set_tooltip_text(POSITIONS[key][0])
            toggle.set_size_request(-1, 34)
            toggle.set_active(key == self.position)
            toggle.connect("toggled", self._position_selected, key)
            grid.attach(toggle, col, row, 1, 1)
            self.position_buttons[key] = toggle
        grid.attach(Gtk.Label(label="Foto"), 1, 1, 1, 1)
        side.pack_start(grid, False, False, 0)
        self.position_label = label(POSITIONS[self.position][0], dim=True)
        side.pack_start(self.position_label, False, False, 0)
        margin_line = Gtk.Box(spacing=8)
        margin_line.pack_start(label("Margen"), True, True, 0)
        self.margin = Gtk.SpinButton.new_with_range(0, 100000, 1)
        self.margin.set_value(100)
        margin_line.pack_start(self.margin, False, False, 0)
        margin_line.pack_start(label("px"), False, False, 0)
        side.pack_start(margin_line, False, False, 0)
        side.pack_start(label("El mismo margen en los bordes de la posición elegida.", dim=True), False, False, 0)
        side.pack_start(section("Opacidad"), False, False, 0)
        self.opacity = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.opacity.set_value(100)
        self.opacity.set_digits(0)
        side.pack_start(self.opacity, False, False, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.pack2(right, resize=True, shrink=False)
        main_scroll = Gtk.ScrolledWindow()
        main_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        right.pack_start(main_scroll, True, True, 0)
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        main.set_border_width(18)
        main_scroll.add(main)
        preview_heading = Gtk.Box(spacing=8)
        preview_heading.pack_start(section("Vista previa"), True, True, 0)
        preview_heading.pack_start(label("Selecciona una foto de la lista", dim=True), False, False, 0)
        main.pack_start(preview_heading, False, False, 0)
        self.preview_area = Gtk.EventBox()
        self.preview_area.set_name("photo-preview")
        self.preview_area.set_size_request(360, 210)
        provider = Gtk.CssProvider()
        provider.load_from_data(b"#photo-preview { background-color: #242830; border-radius: 8px; }")
        self.preview_area.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.preview_image = Gtk.Image.new_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)
        # Overlay children do not enlarge the window when a preview pixbuf changes.
        overlay = Gtk.Overlay()
        overlay.add(Gtk.Box())
        overlay.add_overlay(self.preview_image)
        self.preview_image.set_halign(Gtk.Align.CENTER)
        self.preview_image.set_valign(Gtk.Align.CENTER)
        self.preview_area.add(overlay)
        self.preview_area.connect("size-allocate", self._preview_resized)
        main.pack_start(self.preview_area, True, True, 0)
        self.preview_info = label("Añade fotografías para comprobar el tamaño y la posición.", dim=True)
        main.pack_start(self.preview_info, False, False, 0)

        self.source_actions = Gtk.Box(spacing=8)
        self.source_actions.pack_start(button("Añadir fotos…", self._add_photos), False, False, 0)
        self.source_actions.pack_start(button("Añadir carpeta…", self._add_photo_folder), False, False, 0)
        self.source_actions.pack_start(button("Quitar", self._remove_photo), False, False, 0)
        self.source_actions.pack_start(button("Vaciar", self._clear_photos), False, False, 0)
        self.photo_count = label("", dim=True)
        self.photo_count.set_halign(Gtk.Align.END)
        self.source_actions.pack_end(self.photo_count, True, True, 0)
        main.pack_start(self.source_actions, False, False, 0)
        self.photos = Gtk.ListStore(str, str, str)
        self.photo_tree = Gtk.TreeView(model=self.photos)
        self.photo_tree.set_search_column(1)
        self.photo_tree.set_tooltip_column(0)
        for title, index in (("Fotografía", 1), ("Resultado", 2)):
            renderer = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, renderer, text=index)
            column.set_expand(True)
            column.set_resizable(True)
            self.photo_tree.append_column(column)
        self.photo_tree.get_selection().connect("changed", self._changed)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(-1, 145)
        scroll.add(self.photo_tree)
        main.pack_start(scroll, False, True, 0)

        self.output_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.output_box.pack_start(section("Guardar copias en"), False, False, 0)
        output_line = Gtk.Box(spacing=8)
        self.output = Gtk.Entry(text=str(PROJECT_ROOT / "resultados"))
        self.output.set_hexpand(True)
        output_line.pack_start(self.output, True, True, 0)
        output_line.pack_start(button("Elegir…", self._choose_output), False, False, 0)
        self.output_box.pack_start(output_line, False, False, 0)
        self.output_format = combo(OUTPUT_FORMATS, "original")
        self.output_box.pack_start(self.output_format, False, False, 0)
        main.pack_start(self.output_box, False, False, 0)
        main.pack_start(label("Se guardan copias con el sufijo _marca. Los archivos existentes se conservan.", dim=True), False, False, 0)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_text("Listo para comenzar")
        self.progress.set_margin_start(18)
        self.progress.set_margin_end(18)
        right.pack_start(self.progress, False, False, 0)
        actions = Gtk.Box(spacing=8)
        self.export_button = button("Aplicar a las fotografías", self._export, suggested=True)
        self.cancel_button = button("Cancelar", self._cancel)
        self.open_output_button = button("Ver carpeta", self._open_output)
        self.report_button = button("Guardar informe…", self._save_report)
        actions.pack_start(self.open_output_button, False, False, 0)
        actions.pack_start(self.report_button, False, False, 0)
        actions.pack_end(self.export_button, False, False, 0)
        actions.pack_end(self.cancel_button, False, False, 0)
        actions.set_margin_start(18)
        actions.set_margin_end(18)
        actions.set_margin_bottom(18)
        right.pack_start(actions, False, False, 0)
        for control, signal in ((self.axis, "changed"), (self.size, "value-changed"),
                                (self.margin, "value-changed"), (self.opacity, "value-changed"),
                                (self.output_format, "changed"), (self.output, "changed")):
            control.connect(signal, self._changed)
        self.unit.connect("changed", self._unit_changed)

    def _show_about(self, *_):
        if self.about_dialog is None:
            dialog = Gtk.AboutDialog(
                title=f"Acerca de {APP_NAME}", transient_for=self,
                modal=True, destroy_with_parent=True, use_header_bar=False,
            )
            dialog.set_program_name(APP_NAME)
            dialog.set_version(__version__)
            dialog.set_comments(APP_DESCRIPTION)
            dialog.set_copyright(COPYRIGHT)
            dialog.set_website(WEBSITE)
            dialog.set_website_label(WEBSITE_LABEL)
            dialog.set_authors([AUTHOR])
            # GTK's GPL_3_0 means "version 3 or later" and includes the no-warranty notice.
            dialog.set_license_type(Gtk.License.GPL_3_0)
            dialog.set_wrap_license(True)
            dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(PROJECT_ROOT / "assets/photo-watermark.svg"), 96, 96, True))
            dialog.set_title(f"Acerca de {APP_NAME}")
            dialog.connect("response", lambda widget, _: widget.hide())
            dialog.connect("delete-event", lambda widget, _: widget.hide() or True)
            self.about_dialog = dialog
        self.about_dialog.present()

    def _notify(self, text, message_type=Gtk.MessageType.ERROR):
        if self._closing:
            return
        self.notice.set_message_type(message_type)
        self.notice_label.set_text(text)
        self.notice.show_all()

    def _settings(self) -> Settings:
        self.size.update()
        self.margin.update()
        settings = Settings(self.axis.get_active_id(), self.unit.get_active_id(),
                            self.size.get_value(), self.position,
                            self.margin.get_value_as_int(), self.opacity.get_value())
        settings.validate()
        return settings

    def _unit_changed(self, *_):
        pixels = self.unit.get_active_id() == "px"
        self.size.set_range(1 if pixels else 0.1, 100000 if pixels else 100)
        self.size.set_digits(0 if pixels else 1)
        self.size.set_increments(1 if pixels else 0.1, 50 if pixels else 5)
        if pixels:
            self.size.set_value(int(self.size.get_value() + 0.5))
        self.size_suffix.set_text("px" if pixels else "%")
        self._changed()

    def _position_selected(self, toggle, key):
        if self._applying:
            return
        if not toggle.get_active():
            if self.position == key:
                toggle.set_active(True)
            return
        self._applying = True
        self.position = key
        for other, widget in self.position_buttons.items():
            widget.set_active(other == key)
        self._applying = False
        self.position_label.set_text(POSITIONS[key][0])
        self._changed()

    def _changed(self, *_):
        if not self._ready or self._applying or self._closing:
            return
        dimension = "ancho" if self.axis.get_active_id() == "width" else "alto"
        if self.unit.get_active_id() == "percent":
            self.size_hint.set_text(f"Porcentaje del {dimension} de cada fotografía. El otro lado mantiene la proporción del logo.")
        else:
            self.size_hint.set_text(f"{dimension.capitalize()} fijo en píxeles. El otro lado mantiene la proporción del logo.")
        self._preview_generation += 1
        if self._preview_timer:
            GLib.source_remove(self._preview_timer)
        self._preview_timer = GLib.timeout_add(180, self._start_preview)
        if self._save_timer:
            GLib.source_remove(self._save_timer)
        self._save_timer = GLib.timeout_add(600, self._persist)

    def _persist(self):
        self._save_timer = 0
        try:
            state = self.store.snapshot(self.logo_path, self._settings(), self.output_format.get_active_id())
            state["output"] = self.output.get_text()
            self.store.state["last"] = state
            self.store.save()
        except Exception as exc:
            self._notify(f"No se pudo guardar la configuración: {exc}", Gtk.MessageType.WARNING)
        return False

    def _restore(self, state):
        if not state:
            return
        try:
            if not isinstance(state, dict):
                raise WatermarkError("La configuración guardada no es válida.")
            settings = Settings(**state.get("settings", {}))
            settings.validate()
            output_format = state.get("format", "original")
            if output_format not in OUTPUT_FORMATS:
                raise WatermarkError("Formato guardado desconocido.")
            for field in ("logo", "output"):
                if field in state and not isinstance(state[field], str):
                    raise WatermarkError(f"La ruta guardada de {field} no es válida.")
        except (TypeError, ValueError) as exc:
            self._notify(f"No se puede cargar esta configuración: {exc}", Gtk.MessageType.WARNING)
            return
        self._applying = True
        self.axis.set_active_id(settings.axis)
        self.unit.set_active_id(settings.unit)
        self._unit_changed()
        self.size.set_value(settings.size)
        self.margin.set_value(settings.margin)
        self.opacity.set_value(settings.opacity)
        self.position = settings.position
        for key, toggle in self.position_buttons.items():
            toggle.set_active(key == self.position)
        self.position_label.set_text(POSITIONS[self.position][0])
        self.output_format.set_active_id(output_format)
        if state.get("output"):
            self.output.set_text(state["output"])
        path = Path(state["logo"]) if state.get("logo") else None
        if path and path.is_file():
            self._set_logo(path)
        elif path:
            self.logo_path = None
            self.logo_label.set_text("Logo guardado no disponible")
            self.logo_image.clear()
            self._notify(f"No se encuentra el logo guardado: {path}. Selecciona otro.", Gtk.MessageType.WARNING)
        self._applying = False
        self._refresh_count()
        self._changed()

    def _refresh_presets(self):
        self._applying = True
        self.presets.remove_all()
        self.presets.append("current", "Configuración actual")
        for name in sorted(self.store.state["presets"], key=str.casefold):
            self.presets.append("preset:" + name, name)
        self.presets.set_active_id("current")
        self._applying = False

    def _preset_selected(self, *_):
        if self._applying:
            return
        key = self.presets.get_active_id()
        if key and key.startswith("preset:"):
            self._restore(self.store.state["presets"][key[7:]])

    def _save_preset(self, *_):
        if self.logo_path is None:
            self._notify("Selecciona un logo antes de guardar la configuración.")
            return
        dialog = Gtk.Dialog(title="Guardar configuración", transient_for=self, modal=True)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        entry = Gtk.Entry(placeholder_text="Nombre de la configuración", activates_default=True)
        entry.set_max_length(80)
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        entry.set_margin_top(16)
        entry.set_margin_bottom(16)
        dialog.get_content_area().add(entry)
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not name:
            return
        if name in self.store.state["presets"] and not self._confirm(
            f"¿Reemplazar la configuración «{name}»?", "La configuración anterior se sustituirá."):
            return
        try:
            self.store.state["presets"][name] = self.store.snapshot(
                self.logo_path, self._settings(), self.output_format.get_active_id())
            self.store.save()
            self._refresh_presets()
            self.presets.set_active_id("preset:" + name)
        except Exception as exc:
            self._notify(str(exc))

    def _delete_preset(self, *_):
        key = self.presets.get_active_id()
        if not key or not key.startswith("preset:"):
            return
        name = key[7:]
        if self._confirm(f"¿Eliminar «{name}»?", "El logo y las fotografías se conservan."):
            del self.store.state["presets"][name]
            try:
                self.store.save()
                self._refresh_presets()
            except Exception as exc:
                self._notify(str(exc))

    def _confirm(self, text, detail):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.YES_NO, text=text)
        dialog.format_secondary_text(detail)
        response = dialog.run()
        dialog.destroy()
        return response == Gtk.ResponseType.YES

    def _reload_logos(self):
        paths = set()
        for folder in self.store.folders:
            if folder.is_dir():
                paths.update(discover_images(folder, logos=True))
        self.logo_paths = sorted(paths, key=lambda p: str(p).casefold())
        self.logo_count.set_text(f"{len(paths)} logos disponibles · PNG, SVG y otros")
        self.choose_logo_button.set_sensitive(bool(paths))
        if self.logo_path is None and self.logo_paths:
            preferred = next((p for p in self.logo_paths if p.name == "00-isologo-transparente.png"), self.logo_paths[0])
            self._set_logo(preferred)

    def _set_logo(self, path):
        self.logo_path = Path(path)
        self.logo_label.set_text(self.logo_path.name)
        self.logo_label.set_tooltip_text(str(self.logo_path))
        try:
            self.logo_image.set_from_pixbuf(pixbuf_from_image(logo_thumbnail(self.logo_path)))
        except Exception as exc:
            self.logo_image.clear()
            self._notify(f"No se puede cargar el logo: {exc}")
        self._refresh_count()
        self._changed()

    def _choose_logo(self, *_):
        self._reload_logos()
        dialog = LogoDialog(self, self.logo_paths, self.logo_path)
        response = dialog.run()
        selected = dialog.selected()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and selected:
            self._set_logo(selected)

    def _file_dialog(self, title, action, extensions=None, multiple=False):
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, action=action)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Seleccionar", Gtk.ResponseType.OK)
        dialog.set_select_multiple(multiple)
        if extensions:
            file_filter = Gtk.FileFilter()
            file_filter.set_name("Imágenes compatibles")
            for extension in sorted(extensions):
                file_filter.add_pattern("*" + extension)
                file_filter.add_pattern("*" + extension.upper())
            dialog.add_filter(file_filter)
        if action == Gtk.FileChooserAction.SELECT_FOLDER:
            dialog.set_create_folders(True)
        dialog.set_current_folder(str(PROJECT_ROOT))
        response = dialog.run()
        values = [Path(path) for path in dialog.get_filenames()] if response == Gtk.ResponseType.OK else []
        dialog.destroy()
        return values

    def _import_logo(self, *_):
        paths = self._file_dialog("Importar logo", Gtk.FileChooserAction.OPEN, LOGO_EXTENSIONS)
        if paths:
            try:
                path = self.store.import_logo(paths[0])
                self._reload_logos()
                self._set_logo(path)
            except Exception as exc:
                self._notify(f"No se pudo importar el logo: {exc}")

    def _add_logo_folder(self, *_):
        paths = self._file_dialog("Añadir carpeta de logos (incluye subcarpetas)", Gtk.FileChooserAction.SELECT_FOLDER)
        if paths:
            try:
                self.store.add_folder(paths[0])
                self._reload_logos()
            except Exception as exc:
                self._notify(str(exc))

    def add_photos(self, paths):
        known = {row[0] for row in self.photos}
        for path in paths:
            path = Path(path).expanduser().resolve()
            if str(path) not in known:
                self.photos.append((str(path), path.name, "Pendiente"))
                known.add(str(path))
        if self.photos and self._selected_photo() is None:
            self.photo_tree.get_selection().select_path(0)
        self._refresh_count()
        self._changed()

    def _add_photos(self, *_):
        self.add_photos(self._file_dialog("Añadir fotografías", Gtk.FileChooserAction.OPEN,
                                         PHOTO_EXTENSIONS, multiple=True))

    def _add_photo_folder(self, *_):
        paths = self._file_dialog("Añadir carpeta de fotografías (incluye subcarpetas)", Gtk.FileChooserAction.SELECT_FOLDER)
        if not paths:
            return
        try:
            output_text = self.output.get_text().strip()
            excluded = [PROJECT_ROOT / "resultados"]
            if output_text:
                output = Path(output_text).expanduser().resolve()
                if output != paths[0].resolve():
                    excluded.append(output)
            found = discover_images(paths[0], exclude=excluded)
            if found:
                self.add_photos(found)
            else:
                self._notify("No se encontraron fotografías JPEG, PNG, WebP o TIFF en esa carpeta.", Gtk.MessageType.INFO)
        except Exception as exc:
            self._notify(str(exc))

    def _selected_photo(self):
        model, tree_iter = self.photo_tree.get_selection().get_selected()
        return Path(model[tree_iter][0]) if tree_iter is not None else None

    def _remove_photo(self, *_):
        _, tree_iter = self.photo_tree.get_selection().get_selected()
        if tree_iter is not None:
            self.photos.remove(tree_iter)
        if self.photos and self._selected_photo() is None:
            self.photo_tree.get_selection().select_path(0)
        self._refresh_count()
        self._changed()

    def _clear_photos(self, *_):
        self.photos.clear()
        self._refresh_count()
        self._changed()

    def _refresh_count(self):
        count = len(self.photos)
        self.photo_count.set_text(f"{count} foto" if count == 1 else f"{count} fotos")
        self.export_button.set_sensitive(bool(count and self.logo_path) and not self.busy)

    def _preview_resized(self, _, allocation):
        size = (allocation.width, allocation.height)
        if size != getattr(self, "_preview_bounds", None):
            self._preview_bounds = size
            self._changed()

    def _start_preview(self):
        self._preview_timer = 0
        if self._closing:
            return False
        path = self._selected_photo()
        if path is None or self.logo_path is None:
            self.preview_image.set_from_icon_name("image-x-generic", Gtk.IconSize.DIALOG)
            self.preview_info.set_text("Añade una fotografía y selecciona un logo para ver el resultado.")
            return False
        try:
            settings = self._settings()
        except Exception as exc:
            self.preview_info.set_text(str(exc))
            return False
        generation = self._preview_generation
        bounds = (max(1, self.preview_area.get_allocated_width() - 24),
                  max(1, self.preview_area.get_allocated_height() - 24))
        if self._preview_future:
            self._preview_future.cancel()
        self.preview_info.set_text("Calculando vista previa…")
        self._preview_future = self.preview_worker.submit(
            self._render_preview, path, self.logo_path, settings, bounds)
        self._preview_future.add_done_callback(lambda future: GLib.idle_add(
            self._show_preview, future, generation))
        return False

    def _render_preview(self, path, logo_path, settings, bounds):
        if path != self._photo_cache_path:
            self._photo_cache = load_photo(path)
            self._photo_cache_path = path
        if logo_path != self._logo_cache_path:
            self._logo_cache = Logo(logo_path)
            self._logo_cache_path = logo_path
        image, placement = preview(self._photo_cache, self._logo_cache, settings, bounds)
        return image, placement, self._photo_cache.size

    def _show_preview(self, future, generation):
        if self._closing or generation != self._preview_generation or future.cancelled():
            return False
        try:
            image, place, photo_size = future.result()
            self.preview_image.set_from_pixbuf(pixbuf_from_image(image))
            self.preview_info.set_text(
                f"Foto: {photo_size[0]} × {photo_size[1]} px   ·   "
                f"Marca: {place.width} × {place.height} px   ·   "
                f"{POSITIONS[self.position][0]}   ·   Margen: {self.margin.get_value_as_int()} px")
        except Exception as exc:
            self.preview_image.set_from_icon_name("dialog-warning", Gtk.IconSize.DIALOG)
            self.preview_info.set_text(str(exc))
        return False

    def _choose_output(self, *_):
        paths = self._file_dialog("Elegir carpeta para las copias", Gtk.FileChooserAction.SELECT_FOLDER)
        if paths:
            self.output.set_text(str(paths[0]))

    def _set_busy(self, busy):
        self.busy = busy
        self.settings_box.set_sensitive(not busy)
        self.source_actions.set_sensitive(not busy)
        self.output_box.set_sensitive(not busy)
        self.cancel_button.set_visible(busy)
        self.cancel_button.set_sensitive(busy)
        self._refresh_count()

    def _export(self, *_):
        if self.busy or not self.photos or self.logo_path is None:
            return
        try:
            settings = self._settings()
            output = self.output.get_text().strip()
            if not output:
                raise WatermarkError("Elige una carpeta para guardar las copias.")
            output_dir = Path(output).expanduser().resolve()
            sources = [Path(row[0]) for row in self.photos]
            output_format = self.output_format.get_active_id()
        except Exception as exc:
            self._notify(str(exc))
            return
        self.notice.hide()
        self.report_button.hide()
        self.open_output_button.hide()
        self.batch_results = []
        self.cancel_event.clear()
        self._set_busy(True)
        self.progress.set_fraction(0)
        self.progress.set_text(f"Preparando {len(sources)} fotografías…")
        for row in self.photos:
            row[2] = "Pendiente"
        self.batch_worker.submit(self._export_worker, sources, self.logo_path,
                                 settings, output_dir, output_format)

    def _export_worker(self, sources, logo_path, settings, output_dir, output_format):
        results = []
        fatal_error = None
        try:
            logo = Logo(logo_path)
            for result in process_batch(sources, logo, settings, output_dir, output_format, self.cancel_event):
                results.append(result)
                GLib.idle_add(self._export_progress, len(results) - 1, result, len(sources))
        except Exception as exc:
            fatal_error = str(exc)
        GLib.idle_add(self._export_done, results, len(sources), output_dir, fatal_error)

    def _export_progress(self, index, result, total):
        if self._closing:
            return False
        self.photos[index][2] = "Error: " + result.error if result.error else "Guardada: " + result.destination.name
        self.progress.set_fraction((index + 1) / total)
        self.progress.set_text(f"{index + 1} de {total} · {result.source.name}")
        return False

    def _export_done(self, results, total, output_dir, fatal_error):
        if self._closing:
            return False
        self.batch_results = results
        self.last_output_dir = output_dir
        self._set_busy(False)
        successes = sum(result.error is None for result in results)
        failures = len(results) - successes
        remaining = total - len(results)
        for index in range(len(results), total):
            self.photos[index][2] = "Sin procesar" if fatal_error else "Cancelada"
        text = f"{successes} guardadas · {failures} errores"
        if remaining:
            text += f" · {remaining} sin procesar"
        self.progress.set_text(text)
        if not remaining:
            self.progress.set_fraction(1)
        self.open_output_button.set_visible(successes > 0)
        self.report_button.set_visible(bool(results))
        if fatal_error:
            self._notify(fatal_error)
        elif failures:
            self._notify("Algunas fotografías no se pudieron procesar. Selecciona cada foto para revisar la vista previa, o guarda el informe con los errores.", Gtk.MessageType.WARNING)
        else:
            self._notify(text + f". Carpeta: {output_dir}", Gtk.MessageType.INFO)
        return False

    def _cancel(self, *_):
        self.cancel_event.set()
        self.cancel_button.set_sensitive(False)
        self.progress.set_text("Terminando la fotografía actual y cancelando las restantes…")

    def _open_output(self, *_):
        if self.last_output_dir:
            try:
                Gio.AppInfo.launch_default_for_uri(self.last_output_dir.as_uri(), None)
            except Exception as exc:
                self._notify(str(exc))

    def _save_report(self, *_):
        dialog = Gtk.FileChooserDialog(title="Guardar informe del lote", transient_for=self,
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons("Cancelar", Gtk.ResponseType.CANCEL, "Guardar", Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name("informe-marcas-de-agua.txt")
        response = dialog.run()
        path = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.OK or not path:
            return
        lines = ["Marcas de agua — informe del lote", self.progress.get_text(),
                 f"Carpeta de salida: {self.last_output_dir}", ""]
        for result in self.batch_results:
            lines.append(f"{result.source}\n  ERROR: {result.error}" if result.error else
                         f"{result.source}\n  GUARDADA: {result.destination}")
        try:
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        except Exception as exc:
            self._notify(str(exc))

    def _close(self, *_):
        if self.busy and not self._confirm("¿Cancelar el lote y cerrar?",
                                          "La fotografía actual terminará de guardarse. Las copias ya guardadas se conservan."):
            return True
        self.cancel_event.set()
        for timer in (self._preview_timer, self._save_timer):
            if timer:
                GLib.source_remove(timer)
        self._preview_timer = self._save_timer = 0
        self._persist()
        self._closing = True
        self.preview_worker.shutdown(wait=False, cancel_futures=True)
        self.batch_worker.shutdown(wait=False, cancel_futures=True)
        return False


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.photo_watermark.Desktop",
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        window = self.get_active_window()
        if window is None:
            window = Window(self, Store())
        window.present()


def run() -> int:
    success, _ = Gtk.init_check(None)
    if not success:
        import sys
        print("No se encontró una sesión gráfica. Ejecuta la aplicación desde Cinnamon o usa el comando batch.", file=sys.stderr)
        return 1
    return Application().run(None)
