import io
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from photo_watermark.core import (Logo, Settings, WatermarkError, calculate_placement,
                                 discover_images, load_photo, preview, process_batch,
                                 save_copy, stamp)


class GeometryTests(unittest.TestCase):
    def test_fixed_width_and_height_keep_proportion(self):
        width = calculate_placement((4000, 3000), (1500, 600), Settings(unit="px", size=750))
        height = calculate_placement((4000, 3000), (1500, 600), Settings(axis="height", unit="px", size=750))
        self.assertEqual((width.width, width.height), (750, 300))
        self.assertEqual((height.width, height.height), (1875, 750))

    def test_percentage_uses_each_photograph(self):
        settings = Settings(axis="height", size=30)
        a = calculate_placement((4000, 3000), (1500, 600), settings)
        b = calculate_placement((3000, 2000), (1500, 600), settings)
        self.assertEqual((a.width, a.height), (2250, 900))
        self.assertEqual((b.width, b.height), (1500, 600))

    def test_all_eight_positions_and_margin(self):
        expected = {"top-left": (100, 100), "top-center": (375, 100),
                    "top-right": (650, 100), "center-left": (100, 350),
                    "center-right": (650, 350), "bottom-left": (100, 600),
                    "bottom-center": (375, 600), "bottom-right": (650, 600)}
        for position, coordinates in expected.items():
            with self.subTest(position=position):
                place = calculate_placement((1000, 800), (250, 100),
                                            Settings(unit="px", size=250, position=position))
                self.assertEqual((place.x, place.y), coordinates)

    def test_centered_axis_ignores_margin(self):
        place = calculate_placement((1000, 1000), (1000, 200),
                                    Settings(unit="px", size=1000, position="top-center", margin=500))
        self.assertEqual((place.x, place.y), (0, 500))

    def test_only_anchored_edges_need_margin(self):
        place = calculate_placement((1000, 1000), (900, 900),
                                    Settings(unit="px", size=900, margin=100, position="top-left"))
        self.assertEqual((place.x, place.y), (100, 100))

    def test_oversize_and_margin_errors_do_not_silently_shrink(self):
        for size, margin in ((1100, 0), (1000, 1), (750, 300)):
            with self.subTest(size=size, margin=margin):
                with self.assertRaisesRegex(WatermarkError, "no cabe"):
                    calculate_placement((1000, 1000), (100, 100),
                                        Settings(unit="px", size=size, margin=margin))

    def test_invalid_settings(self):
        for values in ({"size": 0}, {"size": float("nan")}, {"size": float("inf")},
                       {"size": 101}, {"unit": "px", "size": 1.5}, {"margin": -1},
                       {"margin": 1.5}, {"axis": "depth"}, {"position": "center"},
                       {"unit": "cm"}, {"opacity": -1}, {"opacity": 101}):
            with self.subTest(values=values):
                with self.assertRaises(WatermarkError):
                    Settings(**values).validate()

    def test_rounding_and_minimum_pixel(self):
        place = calculate_placement((101, 101), (10, 5), Settings(size=50, margin=0))
        self.assertEqual((place.width, place.height), (51, 26))
        tiny = calculate_placement((10, 10), (1000, 1), Settings(size=0.1, margin=0))
        self.assertEqual((tiny.width, tiny.height), (1, 1))


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.logo_path = self.root / "logo.png"
        Image.new("RGBA", (20, 10), (255, 0, 0, 128)).save(self.logo_path)
        self.logo = Logo(self.logo_path)
        self.photo_path = self.root / "photo.png"
        Image.new("RGB", (200, 100), "blue").save(self.photo_path)
        self.settings = Settings(unit="px", size=20, margin=5)

    def tearDown(self):
        self.temp.cleanup()

    def test_alpha_is_blended_once_and_original_is_untouched(self):
        photo = load_photo(self.photo_path)
        result, place = stamp(photo, self.logo, self.settings)
        self.assertEqual(result.getpixel((place.x, place.y)), (128, 0, 127, 255))
        self.assertEqual(result.getpixel((0, 0)), (0, 0, 255, 255))
        self.assertEqual(photo.getpixel((place.x, place.y)), (0, 0, 255, 255))

    def test_additional_opacity_respects_logo_alpha(self):
        result, place = stamp(load_photo(self.photo_path), self.logo,
                              Settings(unit="px", size=20, margin=5, opacity=50))
        self.assertEqual(result.getpixel((place.x, place.y)), (64, 0, 191, 255))

    def test_png_keeps_transparent_photo(self):
        photo = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
        result, place = stamp(photo, self.logo, self.settings)
        path = save_copy(result, Path("transparent.png"), self.root / "out")
        with Image.open(path) as saved:
            self.assertEqual(saved.getpixel((0, 0)), (0, 0, 0, 0))
            self.assertEqual(saved.getpixel((place.x, place.y))[3], 128)

    def test_preview_reports_original_pixel_geometry(self):
        photo = load_photo(self.photo_path)
        image, place = preview(photo, self.logo, self.settings, (100, 50))
        self.assertEqual(image.size, (100, 50))
        self.assertEqual((place.width, place.height, place.x, place.y), (20, 10, 175, 85))
        self.assertGreater(image.getpixel((88, 43))[0], 100)

    def test_exif_orientation_before_percentage_and_no_second_rotation(self):
        path = self.root / "rotated.jpg"
        exif = Image.Exif()
        exif[274] = 6
        exif[315] = "Prueba"
        Image.new("RGB", (120, 80), "white").save(path, exif=exif)
        photo = load_photo(path)
        self.assertEqual(photo.size, (80, 120))
        result, place = stamp(photo, self.logo, Settings(axis="height", size=25, margin=0))
        self.assertEqual((place.width, place.height), (60, 30))
        output = save_copy(result, path, self.root / "out")
        with Image.open(output) as saved:
            self.assertEqual(saved.size, (80, 120))
            self.assertNotIn(274, saved.getexif())
            self.assertEqual(saved.getexif()[315], "Prueba")

    def test_existing_files_and_originals_are_never_replaced(self):
        original = self.photo_path.read_bytes()
        existing = self.root / "photo_marca.png"
        existing.write_bytes(b"leave me alone")
        first = save_copy(load_photo(self.photo_path), self.photo_path, self.root)
        second = save_copy(load_photo(self.photo_path), self.photo_path, self.root)
        self.assertEqual(first.name, "photo_marca_2.png")
        self.assertEqual(second.name, "photo_marca_3.png")
        self.assertEqual(existing.read_bytes(), b"leave me alone")
        self.assertEqual(self.photo_path.read_bytes(), original)

    def test_existing_symlinks_are_never_replaced_or_followed(self):
        original = self.photo_path.read_bytes()
        (self.root / "photo_marca.png").symlink_to(self.photo_path)
        output = save_copy(load_photo(self.photo_path), self.photo_path, self.root)
        self.assertEqual(output.name, "photo_marca_2.png")
        self.assertEqual(self.photo_path.read_bytes(), original)

    def test_partial_files_removed_after_encoder_failure(self):
        image = load_photo(self.photo_path)
        with patch.object(Image.Image, "save", side_effect=OSError("encoder failed")):
            with self.assertRaises(OSError):
                save_copy(image, self.photo_path, self.root)
        self.assertFalse((self.root / "photo_marca.png").exists())

    def test_output_formats_and_jpeg_white_background(self):
        image = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
        for name, mode in (("jpeg", "RGB"), ("png", "RGBA"), ("webp", "RGBA"), ("tiff", "RGBA")):
            with self.subTest(format=name):
                path = save_copy(image, self.photo_path, self.root / name, name)
                with Image.open(path) as saved:
                    self.assertEqual(saved.size, image.size)
                    self.assertEqual(saved.mode, mode)
                    if name == "jpeg":
                        self.assertEqual(saved.getpixel((0, 0)), (255, 255, 255))

    def test_raster_logo_cache_returns_independent_images(self):
        first = self.logo.render((40, 20))
        first.putalpha(0)
        second = self.logo.render((40, 20))
        self.assertEqual(second.getpixel((0, 0))[3], 128)

    def test_svg_renders_at_requested_resolution(self):
        path = self.root / "logo.svg"
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
                        '<rect width="20" height="10" fill="red" fill-opacity="0.5"/></svg>')
        try:
            logo = Logo(path)
        except WatermarkError as exc:
            if "instala" in str(exc):
                self.skipTest(str(exc))
            raise
        image = logo.render((751, 376))
        self.assertEqual(logo.size, (20, 10))
        self.assertEqual(image.size, (751, 376))
        self.assertEqual(image.getpixel((300, 150)), (255, 0, 0, 128))

    def test_bad_photo_does_not_abort_batch(self):
        bad = self.root / "broken.jpg"
        bad.write_bytes(b"invalid")
        results = list(process_batch([bad, self.photo_path], self.logo, self.settings, self.root / "out"))
        self.assertIsNotNone(results[0].error)
        self.assertIsNone(results[1].error)
        self.assertTrue(results[1].destination.is_file())

    def test_oversized_photo_error_does_not_abort_batch(self):
        small = self.root / "small.png"
        Image.new("RGB", (10, 10)).save(small)
        results = list(process_batch([small, self.photo_path], self.logo, self.settings, self.root / "out"))
        self.assertIn("no cabe", results[0].error)
        self.assertIsNone(results[1].error)

    def test_cancellation_skips_remaining_photos(self):
        cancel = threading.Event()
        iterator = process_batch([self.photo_path, self.photo_path], self.logo, self.settings,
                                 self.root / "out", cancel=cancel)
        self.assertIsNone(next(iterator).error)
        cancel.set()
        self.assertEqual(list(iterator), [])

    def test_animated_files_rejected(self):
        animated = self.root / "animated.png"
        Image.new("RGB", (10, 10), "red").save(
            animated, save_all=True, append_images=[Image.new("RGB", (10, 10), "blue")])
        with self.assertRaisesRegex(WatermarkError, "varias páginas"):
            load_photo(animated)

    def test_discovery_is_recursive_case_insensitive_and_excludes_output(self):
        folder = self.root / "nested"
        folder.mkdir()
        upper = folder / "file.JPG"
        upper.write_bytes(b"test")
        excluded = self.root / "out"
        excluded.mkdir()
        (excluded / "file.png").write_bytes(b"test")
        (folder / "notes.txt").write_text("test")
        photos = discover_images(self.root, exclude=[excluded])
        self.assertIn(upper, photos)
        self.assertEqual(photos, [self.logo_path, upper, self.photo_path])
        self.assertNotIn(upper, discover_images(self.root, recursive=False))
