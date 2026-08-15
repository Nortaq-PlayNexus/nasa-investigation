"""Unit tests for the hardened pipeline infrastructure.

Run:  python tests/test_pipeline.py   (stdlib unittest, no network)
"""

import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

import numpy as np

import adjudicate
import benchmark
import common
import detect


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

import io

from PIL import Image

import changedet
import metadata
import pds
import photometry
import stack as stackmod
import stereo

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
