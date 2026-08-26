"""Unit tests for the hardened pipeline infrastructure.

Run:  python tests/test_pipeline.py   (stdlib unittest, no network)
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

import adjudicate
import benchmark
import common
import detect
import numpy as np
import overlay


class TestOverlay(unittest.TestCase):
    """Text/annotation overlay detector: flagged vs clean scenes."""

    def _text_scene(self, size=512):
        from PIL import ImageDraw, ImageFont
        rng = np.random.default_rng(4)
        arr = rng.normal(110.0, 6.0, (size, size)).astype(np.float32)
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(im)
        try:
            font = ImageFont.load_default(28)
        except TypeError:
            font = ImageFont.load_default()
        d.text((30, 30), "500 METERS", fill=255, font=font)
        d.text((30, size - 60), "ESP_013948_1410", fill=255, font=font)
        d.rectangle([size - 160, size - 50, size - 40, size - 38], fill=255)
        return np.asarray(im, dtype=np.float32)

    def test_text_scene_flagged(self):
        res = overlay.text_overlay_score(self._text_scene())
        self.assertTrue(res["flagged"],
                        msg="annotated scene must be flagged, got %.2f" % res["score"])
        self.assertGreaterEqual(res["lines"], 1)
        self.assertTrue(res["boxes"])

    def test_terrain_scene_not_flagged(self):
        arr = benchmark.synthetic_scene((512, 512), seed=9)
        res = overlay.text_overlay_score(arr)
        self.assertFalse(res["flagged"],
                         msg="clean terrain must not be flagged, got %.2f" % res["score"])

    def test_flat_scene_not_flagged(self):
        res = overlay.text_overlay_score(np.full((256, 256), 80.0, np.float32))
        self.assertFalse(res["flagged"])

    def test_box_overlaps_any(self):
        boxes = [(100, 100, 50, 20)]
        self.assertTrue(overlay.box_overlaps_any((110, 105, 10, 10), boxes, 0.3))
        self.assertFalse(overlay.box_overlaps_any((0, 0, 10, 10), boxes, 0.3))
        self.assertFalse(overlay.box_overlaps_any((160, 100, 10, 10), boxes, 0.3))


class TestBorderExclusion(unittest.TestCase):
    """Edge band suppression in analyze_array."""

    def _scene(self):
        arr = np.full((400, 400), 40.0, dtype=np.float32)
        yy, xx = np.mgrid[0:400, 0:400]
        arr[(xx - 200) ** 2 + (yy - 200) ** 2 <= 18 ** 2] = 220.0  # centre blob
        arr[4:22, 300:340] = 220.0                                 # edge blob
        return arr

    def test_edge_blob_dropped_with_border_frac(self):
        found = detect.analyze_array(self._scene(), [1], 3.0, 12, 8_000_000,
                                     border_frac=0.05)
        self.assertTrue(any(b["x"] < 150 for b in found) is False or
                        all(b["y"] >= 20 for b in found),
                        msg="no candidate may sit inside the border band")
        for b in found:
            self.assertGreaterEqual(b["y"], 20)
            self.assertLessEqual(b["y"] + b["h"], 380)

    def test_centre_blob_kept(self):
        found = detect.analyze_array(self._scene(), [1], 3.0, 12, 8_000_000,
                                     border_frac=0.05)
        self.assertTrue(any(b["x"] <= 200 <= b["x"] + b["w"] and
                            b["y"] <= 200 <= b["y"] + b["h"] for b in found))

    def test_no_border_frac_keeps_edge(self):
        found = detect.analyze_array(self._scene(), [1], 3.0, 12, 8_000_000)
        self.assertTrue(any(b["y"] < 20 for b in found),
                        msg="without border_frac the edge blob must still be found")

    def test_exclude_boxes(self):
        arr = self._scene()
        found = detect.analyze_array(arr, [1], 3.0, 12, 8_000_000,
                                     exclude_boxes=[(180, 180, 40, 40)])
        self.assertFalse(any(b["x"] + b["w"] > 180 and b["x"] < 220 and
                             b["y"] + b["h"] > 180 and b["y"] < 220 for b in found))


class TestZPvalue(unittest.TestCase):
    def test_zero(self):
        self.assertAlmostEqual(common.z_pvalue(0.0), 0.5, delta=1e-3)

    def test_one_nine_six(self):
        self.assertAlmostEqual(common.z_pvalue(1.96), 0.025, delta=1e-2)

    def test_large(self):
        self.assertLess(common.z_pvalue(6.0), 1e-8)

    def test_negative(self):
        self.assertAlmostEqual(common.z_pvalue(-3.0), 0.5, delta=1e-9)


class TestBH(unittest.TestCase):
    def test_book_example(self):
        p = [0.005, 0.01, 0.5, 0.9]
        q = common.benjamini_hochberg(p)
        self.assertAlmostEqual(q[0], 0.02, places=3)
        self.assertAlmostEqual(q[1], 0.02, places=3)
        self.assertAlmostEqual(q[2], 0.6667, places=3)
        self.assertAlmostEqual(q[3], 0.9, places=3)

    def test_all_equal(self):
        p = [0.05] * 10
        q = common.benjamini_hochberg(p)
        self.assertTrue(all(abs(x - 0.05) < 1e-9 for x in q))

    def test_empty(self):
        self.assertEqual(common.benjamini_hochberg([]), [])

    def test_monotone(self):
        p = [0.01, 0.02, 0.5, 0.9, 0.001]
        q = common.benjamini_hochberg(p)
        order = sorted(range(len(p)), key=lambda i: p[i])
        qsorted = [q[i] for i in order]
        for a, b in zip(qsorted, qsorted[1:]):
            self.assertLessEqual(a, b + 1e-9)


class TestValidation(unittest.TestCase):
    def test_in_bounds(self):
        self.assertTrue(common.validate_box(10, 10, 20, 20, 100, 100))

    def test_out_of_bounds(self):
        self.assertFalse(common.validate_box(90, 90, 20, 20, 100, 100))
        self.assertFalse(common.validate_box(-1, 0, 10, 10, 100, 100))

    def test_bad_types(self):
        self.assertFalse(common.validate_box("a", 0, 10, 10, 100, 100))
        self.assertFalse(common.validate_box(None, 0, 10, 10, 100, 100))

    def test_zero_dims(self):
        self.assertFalse(common.validate_box(0, 0, 0, 10, 100, 100))


class TestAtomicAndHash(unittest.TestCase):
    def test_sha256_deterministic(self):
        a = common.sha256_text("hello")
        b = common.sha256_text("hello")
        self.assertEqual(a, b)
        self.assertNotEqual(a, common.sha256_text("hellp"))

    def test_atomic_text_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "sub", "x.txt")
            common.atomic_text_write(p, "alpha")
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), "alpha")

    def test_atomic_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.csv")
            rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
            common.atomic_csv_write(p, rows, ["a", "b"])
            import csv
            with open(p, newline="", encoding="utf-8") as f:
                got = list(csv.DictReader(f))
            self.assertEqual([(int(r["a"]), int(r["b"])) for r in got], [(1, 2), (3, 4)])


class TestBenchmark(unittest.TestCase):
    def test_gaussian_disk_shape(self):
        d = benchmark.gaussian_disk(16, 200.0)
        self.assertEqual(d.shape, (16, 16))
        self.assertGreater(d.max(), 150.0)
        self.assertAlmostEqual(d.max(), d[8, 8], delta=1e-2)

    def test_inject_blobs(self):
        arr = np.zeros((100, 100), dtype=np.float32)
        out = benchmark.inject_blobs(arr, [(50, 50, 20, 150.0)])
        self.assertGreater(out.max(), 100.0)

    def test_place_blobs_all_valid(self):
        blobs = benchmark.place_blobs((400, 400), [16, 32], seed=7)
        self.assertTrue(blobs)
        for cx, cy, size, peak in blobs:
            box = benchmark.blob_box((cx, cy, size, peak))
            self.assertTrue(common.validate_box(*box, 400, 400))

    def test_iou(self):
        a = {"x": 0, "y": 0, "w": 10, "h": 10}
        b = (0, 0, 10, 10)
        self.assertAlmostEqual(benchmark.iou(a, b), 1.0)
        self.assertEqual(benchmark.iou(a, (20, 20, 10, 10)), 0.0)

    def test_synthetic_scene_deterministic(self):
        s1 = benchmark.synthetic_scene((200, 200), seed=3)
        s2 = benchmark.synthetic_scene((200, 200), seed=3)
        s3 = benchmark.synthetic_scene((200, 200), seed=4)
        np.testing.assert_array_equal(s1, s2)
        self.assertFalse(np.array_equal(s1, s3))


class TestDetect(unittest.TestCase):
    def _write_img(self, d, arr):
        p = os.path.join(d, "img.png")
        from PIL import Image
        Image.fromarray(arr.astype(np.uint8)).save(p)
        return p

    def test_detects_bright_blob(self):
        with tempfile.TemporaryDirectory() as d:
            arr = np.full((512, 512), 30.0, dtype=np.float32)
            yy, xx = np.mgrid[0:512, 0:512]
            arr[(xx - 200) ** 2 + (yy - 200) ** 2 <= 20 ** 2] = 200.0
            p = self._write_img(d, arr)
            boxes = detect.analyze(p, [2], 3.0, 12, 8_000_000)
            self.assertTrue(boxes)
            cx, cy = 200, 200
            hit = any(b["x"] <= cx <= b["x"] + b["w"] and
                      b["y"] <= cy <= b["y"] + b["h"] for b in boxes)
            self.assertTrue(hit)

    def test_flat_scene_no_detections(self):
        with tempfile.TemporaryDirectory() as d:
            arr = np.full((512, 512), 100.0, dtype=np.float32)
            p = self._write_img(d, arr)
            boxes = detect.analyze(p, [2, 4], 3.0, 12, 8_000_000)
            self.assertEqual(boxes, [])

    def test_benchmark_recall_floor(self):
        with tempfile.TemporaryDirectory() as d:
            arr = benchmark.synthetic_scene((600, 600), seed=11)
            recall, neg, _ = benchmark.run_bench(
                arr, [24, 64], [4], 3.0, 12, 11, d, "unit")
            self.assertEqual(neg, 0)
            for size in (24, 64):
                hit_n, n = recall[size]
                self.assertEqual(hit_n, n, msg="size %d should be fully recalled" % size)


class TestAdjudicate(unittest.TestCase):
    def _crop(self, size=64, disk_r=8, peak=90.0):
        crop = np.full((size, size), 100.0, dtype=np.float32)
        yy, xx = np.mgrid[0:size, 0:size]
        crop[(xx - size / 2) ** 2 + (yy - size / 2) ** 2 <= disk_r ** 2] += peak
        return crop

    def test_roundness_disk(self):
        crop = self._crop()
        compact, area, per = adjudicate.roundness(crop, 16, 16, 32, 32)
        self.assertGreaterEqual(compact, 0.7)
        self.assertGreater(area, 100.0)

    def test_roundness_noise(self):
        rng = np.random.default_rng(1)
        crop = rng.normal(100.0, 2.0, (64, 64)).astype(np.float32)
        compact, area, per = adjudicate.roundness(crop, 8, 8, 48, 48)
        self.assertLessEqual(compact, 0.6)

    def test_persistence_extended(self):
        crop = self._crop()
        persist, bg = adjudicate.median_persist(crop, 16, 16, 32, 32)
        self.assertGreaterEqual(persist, 0.5)

    def test_persistence_hot_pixel(self):
        crop = np.full((64, 64), 100.0, dtype=np.float32)
        crop[32, 32] = 255.0
        persist, bg = adjudicate.median_persist(crop, 30, 30, 4, 4)
        self.assertLess(persist, 0.35, msg="a lone hot pixel must not survive denoising")

    def test_verdict_funnel(self):
        self.assertEqual(adjudicate.verdict(80, 1, 0, 0.9, 1.0, "", 500),
                         "EXPLAINED-ARTIFACT")
        self.assertEqual(adjudicate.verdict(80, 3, 1, 0.9, 1.0, "", 500),
                         "CONFIRMED-LEAD")
        self.assertEqual(adjudicate.verdict(80, 3, 1, 0.9, 1.0, "streak", 500),
                         "TERRAIN")
        self.assertEqual(adjudicate.verdict(50, 3, 0, 0.9, 1.0, "", 500),
                         "PROMISING")
        self.assertEqual(adjudicate.verdict(30, 3, 0, 0.3, 4.0, "", 500),
                         "WEAK")
        self.assertEqual(adjudicate.verdict(10, 3, 0, 0.3, 4.0, "", 500),
                         "NOISE")

    def test_sibling_groups_only_multi(self):
        recs = {
            0: {"stem": "S", "W": 100, "H": 100, "path": "a.png"},
            1: {"stem": "S", "W": 100, "H": 100, "path": "b.png"},
            2: {"stem": "S", "W": 100, "H": 100, "path": "a.png"},
            3: {"stem": "S", "W": 50, "H": 50, "path": "c.png"},
        }
        groups = adjudicate.sibling_groups(recs)
        self.assertIn(("S", 100, 100), groups)
        self.assertNotIn(("S", 50, 50), groups)
        self.assertEqual(groups[("S", 100, 100)], ["a.png", "b.png"])


# --------------------------------------------------------------------------
# New capability tests: native PDS ingestion, solar geometry, photometry,
# stereo, change detection, annulus detector, stacking, geometry scoring.
# --------------------------------------------------------------------------


import changedet  # noqa: E402
import metadata  # noqa: E402
import pds  # noqa: E402
import photometry  # noqa: E402
import stack as stackmod  # noqa: E402
import stereo  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402

LABEL_RECORD_BYTES = 4096


def _attached_bytes(mask_bits="2#1111111111111111#", data=None, record_bytes=LABEL_RECORD_BYTES):
    label = (
        "PDS_VERSION_ID = PDS3\n"
        "RECORD_TYPE = FIXED_LENGTH\n"
        "RECORD_BYTES = %d\n"
        "FILE_RECORDS = 1\n"
        "^IMAGE = 1\n"
        "\n"
        "OBJECT = IMAGE\n"
        "  LINES = 8\n"
        "  LINE_SAMPLES = 8\n"
        "  SAMPLE_TYPE = MSB_UNSIGNED_INTEGER\n"
        "  SAMPLE_BITS = 16\n"
        "  BAND_STORAGE_TYPE = BSQ\n"
        "  SAMPLE_BIT_MASK = %s\n"
        "  INCIDENCE_ANGLE = 34.5\n"
        "  EMISSION_ANGLE = 2.0\n"
        "  PHASE_ANGLE = 33.0\n"
        "  SOLAR_AZIMUTH_ANGLE = 135.0\n"
        "  PIXEL_SCALE = 0.5\n"
        "  SPACECRAFT_ALTITUDE = 300000.0\n"
        "  TARGET_NAME = MARS\n"
        "  INSTRUMENT_ID = CTX\n"
        "  OBSERVATION_ID = TEST_0001\n"
        "END_OBJECT = IMAGE\n"
        "END\n" % (record_bytes, mask_bits)
    ).encode("ascii")
    pad = record_bytes - len(label)
    if pad < 0:
        raise RuntimeError("label text overflows the record")
    if data is None:
        data = (np.arange(64, dtype=np.uint16).reshape(8, 8).astype(">u2")).tobytes()
    return label + b"\x00" * pad + data


DETACHED_LABEL = (
    "PDS_VERSION_ID = PDS3\n"
    "^IMAGE = \"image.img\"\n"
    "\n"
    "OBJECT = IMAGE\n"
    "  LINES = 8\n"
    "  LINE_SAMPLES = 8\n"
    "  SAMPLE_TYPE = MSB_UNSIGNED_INTEGER\n"
    "  SAMPLE_BITS = 16\n"
    "  BAND_STORAGE_TYPE = BSQ\n"
    "  INCIDENCE_ANGLE = 34.5\n"
    "  EMISSION_ANGLE = 2.0\n"
    "  PHASE_ANGLE = 33.0\n"
    "  SOLAR_AZIMUTH_ANGLE = 135.0\n"
    "  PIXEL_SCALE = 0.5\n"
    "  SPACECRAFT_ALTITUDE = 300000.0\n"
    "  TARGET_NAME = MARS\n"
    "  INSTRUMENT_ID = CTX\n"
    "  OBSERVATION_ID = TEST_0001\n"
    "END_OBJECT = IMAGE\n"
    "END\n"
)


class TestPDS(unittest.TestCase):
    def test_parse_attached_label_flat(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "attached.img")
            with open(path, "wb") as f:
                f.write(_attached_bytes())
            data = pds.parse_label(path)
            self.assertEqual(data["^IMAGE"], 1)
            flat = pds.label_flat(data)
            self.assertEqual(flat["SAMPLE_BITS"], 16)
            self.assertEqual(flat["OBSERVATION_ID"], "TEST_0001")

    def test_read_attached_image(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "attached.img")
            with open(path, "wb") as f:
                f.write(_attached_bytes())
            arr = pds.read_image(path)
            self.assertEqual(arr.shape, (8, 8))
            self.assertAlmostEqual(float(arr[0, 0]), 0.0)
            self.assertAlmostEqual(float(arr[7, 7]), 63.0)

    def test_read_detached_image(self):
        with tempfile.TemporaryDirectory() as td:
            lbl = os.path.join(td, "img.lbl")
            with open(lbl, "w", encoding="utf-8") as f:
                f.write(DETACHED_LABEL)
            with open(os.path.join(td, "image.img"), "wb") as f:
                f.write((np.arange(64, dtype=np.uint16).reshape(8, 8).astype(">u2")).tobytes())
            arr = pds.read_image(lbl)
            self.assertEqual(arr.shape, (8, 8))
            self.assertAlmostEqual(float(arr[1, 1]), 9.0)

    def test_bit_mask_shift(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "masked.img")
            data = (np.arange(64, dtype=np.uint16).reshape(8, 8) * 16).astype(">u2").tobytes()
            with open(path, "wb") as f:
                f.write(_attached_bytes(mask_bits="2#1111111111110000#", data=data))
            arr = pds.read_image(path)
            self.assertAlmostEqual(float(arr.max()), 63.0)  # (1008 & 0xFFF0) >> 4
            self.assertAlmostEqual(float(arr[7, 7]), 63.0)

    def test_image_geometry(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "attached.img")
            with open(path, "wb") as f:
                f.write(_attached_bytes())
            g = pds.image_geometry(path)
            self.assertEqual(g[:2], (8, 8))


class TestMetadata(unittest.TestCase):
    def test_bearing_east(self):
        self.assertAlmostEqual(metadata.bearing(0, 0, 0, 90), 90.0, places=6)

    def test_solar_elevation(self):
        self.assertEqual(metadata.solar_elevation(60), 30.0)

    def test_shadow_roundtrip(self):
        h = metadata.height_from_shadow_len(10.0, 45.0, 1.0)
        self.assertAlmostEqual(h, 10.0, places=4)
        s = metadata.shadow_len_for_height(h, 45.0, 1.0)
        self.assertAlmostEqual(s, 10.0, places=4)

    def test_geometry_from_label(self):
        data = pds.parse_label(DETACHED_LABEL)
        g = metadata.geometry_from_label(data)
        self.assertEqual(g["solar_elevation"], 55.5)  # 90 - 34.5
        self.assertEqual(g["solar_azimuth"], 135.0)
        self.assertEqual(g["pixel_scale_m"], 0.5)
        self.assertEqual(g["spacecraft_altitude_km"], 300.0)  # m -> km
        self.assertEqual(g["target"], "MARS")


class TestPhotometry(unittest.TestCase):
    def test_sun_ground_vector_zenith(self):
        nx, ny, nz = photometry.sun_ground_vector(90.0, 0.0)
        self.assertAlmostEqual(nx, 0.0, places=6)
        self.assertAlmostEqual(ny, 0.0, places=6)
        self.assertAlmostEqual(nz, 1.0, places=6)

    def test_shadow_direction(self):
        d = photometry.shadow_direction(0.0)  # sun at north -> shadow south
        self.assertAlmostEqual(d[0], 0.0, places=6)
        self.assertAlmostEqual(d[1], 1.0, places=6)
        mag = (d[0] ** 2 + d[1] ** 2) ** 0.5
        self.assertAlmostEqual(mag, 1.0, places=6)

    def test_shadow_alignment_aligned_vs_misaligned(self):
        crop = np.zeros((64, 64), np.float32)
        crop[12:52, 30:34] = 200.0  # bright vertical bar (north-south)
        good = photometry.shadow_alignment(crop, 0.0, polarity="bright")  # axis ~90 deg
        self.assertFalse(good["skipped"])
        self.assertGreater(good["score"], 0.6)
        crop2 = np.zeros((64, 64), np.float32)
        crop2[30:34, 12:52] = 200.0  # horizontal bar
        bad = photometry.shadow_alignment(crop2, 0.0, polarity="bright")
        self.assertLess(bad["score"], 0.3)

    def test_lambert_normalize_flat(self):
        img = np.full((16, 16), 100.0, np.float32)
        out = photometry.lambert_normalize(img, 0.0)
        self.assertAlmostEqual(float(out[0, 0]), 100.0, places=4)


class TestStereo(unittest.TestCase):
    def test_disparity_recovers_shift(self):
        rng = np.random.RandomState(7)
        base = rng.rand(96, 96).astype(np.float32) * 50
        shifted = np.roll(np.roll(base, 3, axis=0), 2, axis=1)
        bdx, bdy, ssd = stereo.disparity_map(base, shifted, block=11, search=24)
        win = (slice(24, 72), slice(24, 72))
        self.assertAlmostEqual(abs(float(np.median(bdx[win]))), 2.0, delta=0.5)
        self.assertAlmostEqual(abs(float(np.median(bdy[win]))), 3.0, delta=0.5)

    def test_height_from_disparity_monotone(self):
        a = stereo.height_from_disparity(2.0, 300000.0, 1200.0, 700.0)
        b = stereo.height_from_disparity(4.0, 300000.0, 1200.0, 700.0)
        self.assertTrue(a > 0)
        self.assertGreater(b, a)

    def test_anaglyph_shape(self):
        a = stereo.anaglyph(np.zeros((8, 8), np.float32), np.zeros((8, 8), np.float32))
        self.assertEqual(a.shape, (8, 8, 3))


class TestChangedet(unittest.TestCase):
    def test_phase_correlate_shift(self):
        rng = np.random.RandomState(11)
        a = rng.rand(128, 128).astype(np.float32)
        b = changedet.shift_image(a, 5, -3)
        dy, dx, score = changedet.phase_correlate(a, b)
        self.assertAlmostEqual(dy, -5, delta=1)  # align b onto a: up 5
        self.assertAlmostEqual(dx, 3, delta=1)   # align b onto a: right 3
        self.assertGreater(score, 0.3)

    def test_register_no_change(self):
        base = np.full((64, 64), 100.0, np.float32)
        cand, _ = changedet.register_and_changes(base, base.copy(), min_size=8)
        self.assertEqual(cand, [])

    def test_register_and_changes_finds_injection(self):
        rng = np.random.RandomState(13)
        base = rng.rand(128, 128).astype(np.float32) * 50
        other = base.copy()
        other[40:44, 60:64] += 40.0
        cand, (dy, dx, score) = changedet.register_and_changes(base, other, min_size=8)
        self.assertTrue(cand)
        c = cand[0]
        self.assertTrue(36 <= c["y"] <= 48)
        self.assertTrue(56 <= c["x"] <= 68)


class TestDetectAnnulus(unittest.TestCase):
    def test_annulus_flags_embedded_blob(self):
        rng = np.random.RandomState(3)
        arr = (rng.rand(64, 64) * 20).astype(np.float32)
        arr[24:30, 24:30] = 200.0
        field = detect.local_contrast_field(arr, rin=4, rout=10)
        self.assertGreater(field[26, 26], 3.0)
        self.assertLess(abs(float(field[50, 50])), 2.0)

    def test_analyze_array_both_methods(self):
        rng = np.random.RandomState(5)
        arr = (rng.rand(96, 96) * 20).astype(np.float32)
        arr[40:50, 60:70] = 250.0
        for method in ("box", "annulus"):
            found = detect.analyze_array(arr, scales=[1, 2], z=3.0, min_size=20,
                                         max_scale_pixels=12_000_000, method=method)
            self.assertTrue(any(f["x"] + f["w"] >= 60 and f["x"] <= 70 for f in found),
                            "method %s missed the blob" % method)

    def test_analyze_propagates_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "probe.png")
            Image.fromarray(np.zeros((96, 96), np.uint8)).save(p)
            arr = (np.random.RandomState(1).rand(96, 96) * 20).astype(np.float32)
            arr[40:50, 60:70] = 250.0
            Image.fromarray(arr.astype(np.uint8)).save(p)
            found = detect.analyze(p, [1], 3.0, 20, 12_000_000)
            self.assertTrue(found)
            for f in found:
                self.assertEqual(f["path"], p)
                self.assertEqual(f["image"], os.path.basename(p))


class TestStack(unittest.TestCase):
    def test_sigma_clip_removes_outlier(self):
        frames = [np.full((16, 16), 100.0, np.float32) for _ in range(7)]
        frames[0][5, 5] = 1000.0
        out = stackmod.sigma_clip_stack(frames, clip=3.0)
        self.assertAlmostEqual(float(out[5, 5]), 100.0, delta=1.0)

    def test_destripe_removes_column_offset(self):
        arr = np.full((32, 32), 50.0, np.float32)
        arr[:, 17] += 25.0
        out = stackmod.destripe(arr, tol=3.0)
        self.assertAlmostEqual(float(out[10, 17]), 50.0, delta=1.0)
        self.assertAlmostEqual(float(out[10, 16]), 50.0, delta=0.5)


class TestAdjudicateGeometry(unittest.TestCase):
    def test_solar_geometry_scoring(self):
        base = dict(interest=50.0, agrees=0, persistence=0.7, compact=0.8,
                    near_edge=False, flags="", bg_std=6.0)
        good = adjudicate.adjudicated_score(**base, shadow_align=0.9,
                                            shadow_expected=True, size_m=500.0)
        bad = adjudicate.adjudicated_score(**base, shadow_align=0.1,
                                           shadow_expected=True, size_m=500.0)
        huge = adjudicate.adjudicated_score(**base, shadow_align=0.9,
                                            shadow_expected=True, size_m=50000.0)
        self.assertGreater(good, bad)
        self.assertGreater(good, huge)
        adjudicate.adjudicated_score(**base)  # default path does not crash


class TestCommonIO(unittest.TestCase):
    def test_image_dims_png(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "x.png")
            Image.fromarray(np.zeros((30, 45), np.uint8)).save(p)
            self.assertEqual(common.image_dims(p), (45, 30))

    def test_load_gray_16bit_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "y.png")
            a16 = (np.arange(256 * 256, dtype=np.uint16).reshape(256, 256)) % 40000
            Image.fromarray(a16).save(p)
            g = common.load_gray(p)
            self.assertEqual(g.shape, (256, 256))
            self.assertGreater(float(g.max()), 4000.0)

    def test_audit_path_for_normalizes(self):
        p = common.audit_path_for(os.path.join("data", "anomalies", "conclusions"))
        self.assertFalse(".." in p.split(os.sep))
        self.assertTrue(p.endswith("audit.jsonl"))


# --------------------------------------------------------------------------
# Upgrades: multi-band PDS cubes, vectorized shifts, extra artifact checks,
# scipy-free morphology fallback, benchmark temp-file hygiene.
# --------------------------------------------------------------------------

import analyze  # noqa: E402


def _cube_label(bands, storage, prefix=0, lines=4, samples=4):
    label = (
        "PDS_VERSION_ID = PDS3\n"
        "RECORD_TYPE = FIXED_LENGTH\n"
        "RECORD_BYTES = 4096\n"
        "^IMAGE = 1\n"
        "\n"
        "OBJECT = IMAGE\n"
        "  LINES = %d\n"
        "  LINE_SAMPLES = %d\n"
        "  BANDS = %d\n"
        "  SAMPLE_TYPE = MSB_UNSIGNED_INTEGER\n"
        "  SAMPLE_BITS = 16\n"
        "  BAND_STORAGE_TYPE = %s\n"
        % (lines, samples, bands, storage)
    )
    if prefix:
        label += "  LINE_PREFIX_BYTES = %d\n" % prefix
    label += "END_OBJECT = IMAGE\nEND\n"
    return label.encode("ascii")


def _cube_bytes_for(b0, b1, storage, prefix):
    def pre(n):
        return np.full(n, 0xEE, dtype=np.uint16)
    lines = b0.shape[0]
    if storage == "BAND_SEQUENTIAL":
        return np.concatenate([np.concatenate([pre(prefix), r])
                               for band in (b0, b1) for r in band])
    if storage == "LINE_INTERLEAVED":
        return np.concatenate([np.concatenate([pre(prefix), b0[i], b1[i]])
                               for i in range(lines)])
    row = []
    for i in range(lines):
        row.append(pre(prefix))
        for j in range(b0.shape[1]):
            row.append(np.array([b0[i, j], b1[i, j]], dtype=np.uint16))
    return np.concatenate(row)


class TestPDSMultiband(unittest.TestCase):
    def _write_cube(self, td, storage, prefix=0):
        b0 = np.arange(16, dtype=np.uint16).reshape(4, 4)
        b1 = (100 + np.arange(16, dtype=np.uint16)).reshape(4, 4)
        lbl = _cube_label(2, storage, prefix)
        blob = lbl + b"\x00" * (4096 - len(lbl)) + \
            _cube_bytes_for(b0, b1, storage, prefix).astype(">u2").tobytes()
        path = os.path.join(td, "cube.img")
        with open(path, "wb") as f:
            f.write(blob)
        return path, b0, b1

    def test_all_storage_types(self):
        shapes = {"BAND_SEQUENTIAL": (2, 4, 4),
                  "LINE_INTERLEAVED": (4, 2, 4),
                  "SAMPLE_INTERLEAVED": (4, 4, 2)}
        for storage, want_shape in shapes.items():
            with tempfile.TemporaryDirectory() as td:
                path, b0, b1 = self._write_cube(td, storage)
                arr = pds.read_image(path)
                self.assertEqual(arr.shape, want_shape, msg=storage)
                band1 = arr[1] if storage == "BAND_SEQUENTIAL" else (
                    arr[:, 1, :] if storage == "LINE_INTERLEAVED" else arr[:, :, 1])
                np.testing.assert_array_equal(band1, b1.astype(np.float32))

    def test_band_selection_and_read_band(self):
        with tempfile.TemporaryDirectory() as td:
            path, _, b1 = self._write_cube(td, "BAND_SEQUENTIAL")
            np.testing.assert_array_equal(
                pds.read_image(path, band=1), b1.astype(np.float32))
            np.testing.assert_array_equal(
                pds.read_band(path, 1), b1.astype(np.float32))
            with self.assertRaises(ValueError):
                pds.read_band(path, 5)

    def test_prefix_bytes_skipped_multiband(self):
        for storage in ("BAND_SEQUENTIAL", "LINE_INTERLEAVED", "SAMPLE_INTERLEAVED"):
            with tempfile.TemporaryDirectory() as td:
                path, _, b1 = self._write_cube(td, storage, prefix=2)
                got = pds.read_image(path, band=1)
                np.testing.assert_array_equal(got, b1.astype(np.float32),
                                              err_msg=storage)

    def test_truncated_data_raises(self):
        with tempfile.TemporaryDirectory() as td:
            path, _, _ = self._write_cube(td, "BAND_SEQUENTIAL")
            with open(path, "rb") as f:
                raw = f.read()
            cut = os.path.join(td, "cut.img")
            with open(cut, "wb") as f:
                f.write(raw[:len(raw) - 40])  # drop part of band 2
            with self.assertRaises(ValueError):
                pds.read_image(cut)


class TestChangedetShift(unittest.TestCase):
    def _reference_shift(self, arr, dy, dx):
        h, w = arr.shape
        out = np.zeros_like(arr)
        for sy in range(max(0, dy), min(h, h + dy)):
            for sx in range(max(0, dx), min(w, w + dx)):
                out[sy, sx] = arr[sy - dy, sx - dx]
        return out

    def test_matches_reference_all_directions(self):
        rng = np.random.RandomState(3)
        arr = rng.rand(20, 24).astype(np.float32)
        for dy, dx in ((0, 0), (3, 2), (-3, 2), (3, -2), (-3, -2), (25, 0), (0, -30)):
            np.testing.assert_array_equal(
                changedet.shift_image(arr, dy, dx),
                self._reference_shift(arr, dy, dx),
                err_msg="shift (%d,%d)" % (dy, dx))


class TestAnalyzeFlags(unittest.TestCase):
    def test_corner_flag_near_corner_only(self):
        arr = np.full((200, 200), 50.0, np.float32)
        _, feats_near = analyze.analyze_candidate(
            {"x": 1, "y": 1, "w": 10, "h": 10, "fill": 0.9}, arr, 512)
        _, feats_mid = analyze.analyze_candidate(
            {"x": 95, "y": 95, "w": 10, "h": 10, "fill": 0.9}, arr, 512)
        self.assertTrue(feats_near["in_corner"])
        self.assertFalse(feats_mid["in_corner"])

    def test_column_smear_flagged(self):
        arr = np.full((64, 64), 100.0, np.float32)
        arr[:, 30:32] = 220.0  # bright column through the whole frame
        feats = analyze.measure(arr, 28, 28, 6, 6)
        flags = analyze.artifact_flags(dict(
            feats, area_px=36, aspect=1.0, w=6, h=6, fill=0.33,
            on_grid8=False, near_edge=False, dark_band=False, sat_frac=0.0))
        self.assertIn("column_smear", flags)

    def test_discrete_blob_not_smear_flagged(self):
        arr = np.full((64, 64), 100.0, np.float32)
        arr[28:34, 28:34] = 180.0  # compact blob inside the box only
        feats = analyze.measure(arr, 26, 26, 10, 10)
        self.assertLess(feats["column_smear"], 2.0)
        flags = analyze.artifact_flags(dict(
            feats, area_px=100, aspect=1.0, w=10, h=10, fill=0.36,
            on_grid8=False, near_edge=False, dark_band=False, sat_frac=0.0))
        self.assertNotIn("column_smear", flags)

    def test_wide_column_not_smear_flagged(self):
        arr = np.full((64, 64), 100.0, np.float32)
        arr[:, 20:44] = 200.0  # wide bright band: terrain, not a dead column
        feats = analyze.measure(arr, 22, 28, 20, 8)
        flags = analyze.artifact_flags(dict(
            feats, area_px=160, aspect=2.5, w=20, h=8, fill=1.0,
            on_grid8=False, near_edge=False, dark_band=False, sat_frac=0.0))
        self.assertNotIn("column_smear", flags)


class TestAdjudicateMorphologyFallback(unittest.TestCase):
    def test_roundness_without_scipy(self):
        saved = (adjudicate.HAS_SCIPY, adjudicate._ndimage)
        adjudicate.HAS_SCIPY = False
        adjudicate._ndimage = None
        try:
            crop = np.full((64, 64), 100.0, dtype=np.float32)
            yy, xx = np.mgrid[0:64, 0:64]
            crop[(xx - 32) ** 2 + (yy - 32) ** 2 <= 8 ** 2] += 90.0
            compact, area, per = adjudicate.roundness(crop, 16, 16, 32, 32)
            self.assertGreaterEqual(compact, 0.7)
            self.assertGreater(area, 100.0)
        finally:
            adjudicate.HAS_SCIPY, adjudicate._ndimage = saved

    def test_erode_dilate_roundtrip(self):
        m = np.zeros((16, 16), dtype=bool)
        m[4:12, 4:12] = True
        er = adjudicate._erode8(m)
        self.assertEqual(int(er.sum()), 36)  # 8x8 -> 6x6 under 3x3 erosion
        dl = adjudicate._dilate8(er)
        self.assertEqual(int(dl.sum()), 64)  # back to 8x8


class TestBenchmarkHygiene(unittest.TestCase):
    def test_run_bench_leaves_no_temp_files(self):
        with tempfile.TemporaryDirectory() as d:
            arr = benchmark.synthetic_scene((300, 300), seed=5)
            benchmark.run_bench(arr, [24], [4], 3.0, 12, 5, d, "hygiene")
            leftovers = [f for f in os.listdir(d)
                         if f.startswith("_bench_") or f.startswith("_clean_")]
            self.assertEqual(leftovers, [])


class TestAnalyzeRigor(unittest.TestCase):
    """New sophistication metrics: spectral grid-energy, edge sharpness and
    multi-window contrast stability."""

    def test_grid_energy_separates_periodic_from_noise(self):
        rng = np.random.default_rng(2)
        xx = np.arange(128)
        grid = rng.normal(0, 8, (128, 128)).astype(np.float32)
        # strong vertical periodic structure -> concentrated spectrum
        grid += 50.0 * np.abs(np.sin(2 * np.pi * xx[None, :] / 8.0)).astype(np.float32)
        noise = rng.normal(0, 8, (128, 128)).astype(np.float32)
        g_grid = analyze.grid_energy(grid)
        g_noise = analyze.grid_energy(noise)
        self.assertGreater(g_grid, 0.4, "periodic grid must concentrate spectral power")
        self.assertLess(g_noise, 0.2, "noise must spread power across the spectrum")
        self.assertGreater(g_grid, g_noise * 2)

    def test_edge_sharpness_sharp_beats_blurred(self):
        base = np.full((64, 64), 50.0, np.float32)
        base[30:40, 30:40] = 200.0  # hard-edged square
        blurred = np.asarray(
            Image.fromarray(base.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),
            dtype=np.float32)
        s_sharp = analyze.edge_sharpness(base, 30, 30, 10, 10)
        s_blur = analyze.edge_sharpness(blurred, 30, 30, 10, 10)
        self.assertGreater(s_sharp, s_blur, "a sharp boundary must score higher")

    def test_contrast_stability_extended_beats_hot_pixel(self):
        disk = np.full((64, 64), 100.0, np.float32)
        yy, xx = np.mgrid[0:64, 0:64]
        disk[(xx - 32) ** 2 + (yy - 32) ** 2 <= 8 ** 2] = 190.0
        hot = np.full((64, 64), 100.0, np.float32)
        hot[32, 32] = 255.0
        d = analyze.contrast_stability(disk, 24, 24, 16, 16)
        h = analyze.contrast_stability(hot, 31, 31, 3, 3)
        self.assertGreater(d, 0.4, "an extended feature keeps its contrast "
                           "as the window grows")
        self.assertGreater(d, h, "a lone hot pixel loses contrast when the "
                          "window grows")

    def test_metrics_emitted_by_analyze_candidate(self):
        arr = np.full((200, 200), 60.0, np.float32)
        arr[90:110, 90:110] = 180.0
        _, feats = analyze.analyze_candidate(
            {"x": 90, "y": 90, "w": 20, "h": 20, "fill": 0.8}, arr, 512)
        for key in ("grid_energy", "edge_sharpness", "contrast_stability"):
            self.assertIn(key, feats)
            self.assertIsInstance(feats[key], float)


class TestEnhance(unittest.TestCase):
    """Image enhancement utilities: stretch, to_uint16, is_16bit."""

    def test_stretch_2d(self):
        import enhance
        arr = np.linspace(10, 200, 256 * 256, dtype=np.float32).reshape(256, 256)
        out = enhance.stretch(arr)
        self.assertEqual(out.shape, (256, 256))
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out.min()), 0.0, places=0)
        self.assertAlmostEqual(float(out.max()), 255.0, places=0)

    def test_stretch_3d(self):
        import enhance
        arr = np.full((32, 32, 3), 100.0, dtype=np.float32)
        arr[:, :, 0] = 50.0
        arr[:, :, 2] = 200.0
        out = enhance.stretch(arr)
        self.assertEqual(out.ndim, 3)
        self.assertEqual(out.shape[2], 3)

    def test_is_16bit(self):
        import enhance
        self.assertTrue(enhance.is_16bit(np.zeros((4, 4), dtype=np.float32)))
        self.assertTrue(enhance.is_16bit(np.zeros((4, 4), dtype=np.uint16)))
        self.assertFalse(enhance.is_16bit(np.zeros((4, 4), dtype=np.uint8)))

    def test_to_uint16(self):
        import enhance
        arr = np.linspace(0, 1.0, 100, dtype=np.float32).reshape(10, 10)
        out = enhance.to_uint16(arr)
        self.assertEqual(out.dtype, np.uint16)
        self.assertEqual(out.shape, (10, 10))
        self.assertGreater(out.max(), 0)


class TestTriage(unittest.TestCase):
    """Triage helper functions: fit, draw_boxes."""

    def test_fit_preserves_aspect(self):
        import triage
        from PIL import Image
        im = Image.new("RGB", (400, 200))
        thumb = triage.fit(im, 100)
        self.assertLessEqual(max(thumb.width, thumb.height), 100)
        ratio = thumb.width / thumb.height
        self.assertAlmostEqual(ratio, 2.0, places=1)

    def test_draw_boxes_returns_image(self):
        import triage
        from PIL import Image
        im = Image.new("RGB", (200, 200), (50, 50, 50))
        boxes = [(10, 10, 40, 40), (80, 80, 50, 50)]
        thumb = triage.draw_boxes(im, boxes, 128)
        self.assertEqual(thumb.mode, "RGB")
        self.assertLessEqual(max(thumb.width, thumb.height), 128)


class TestMark(unittest.TestCase):
    """Mark overlay drawing on images."""

    def test_mark_boxes_on_image(self):
        import mark
        from PIL import Image
        import csv as csv_mod
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            im = Image.new("RGB", (100, 100), (80, 80, 80))
            src = os.path.join(td, "src.png")
            im.save(src)
            cands = os.path.join(td, "cands.csv")
            with open(cands, "w", newline="") as f:
                w = csv_mod.writer(f)
                w.writerow(["image", "path", "x", "y", "w", "h", "score", "fill"])
                w.writerow(["src.png", src, "10", "10", "30", "30", "0.9", "0.8"])
            out = os.path.join(td, "marked")
            mark.main(["--candidates", cands, "--out", out])
            self.assertTrue(os.path.exists(os.path.join(out, "marked_src.png")))


class TestExtrasCompare(unittest.TestCase):
    """Variant comparison taxonomy and normalization helpers."""

    def test_taxonomy_red(self):
        import extras_compare
        self.assertIn("B&W", extras_compare._taxonomy("ESP_012345_1234_RED.browse.jpg"))

    def test_taxonomy_irb(self):
        import extras_compare
        self.assertIn("IRB", extras_compare._taxonomy("ESP_012345_1234_IRB.browse.jpg"))

    def test_taxonomy_dtm(self):
        import extras_compare
        self.assertIn("DTM", extras_compare._taxonomy("DTEEC_012345_1234_012345_1234.ca.jpg"))

    def test_variant_role_red(self):
        import extras_compare
        self.assertEqual(extras_compare._variant_role("ESP_012345_1234_RED.browse.jpg"), "red")

    def test_variant_role_dtm(self):
        import extras_compare
        self.assertEqual(extras_compare._variant_role("DTEEC_012345_1234.jp2"), "dtm")

    def test_norm01_basic(self):
        import extras_compare
        arr = np.array([0.0, 50.0, 100.0, 150.0, 200.0], dtype=np.float32)
        out = extras_compare._norm01(arr)
        self.assertEqual(out.dtype, np.float32)
        self.assertAlmostEqual(float(out.min()), 0.0, places=3)
        self.assertAlmostEqual(float(out.max()), 1.0, places=3)

    def test_norm01_empty(self):
        import extras_compare
        arr = np.array([], dtype=np.float32)
        out = extras_compare._norm01(arr)
        self.assertEqual(out.size, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
