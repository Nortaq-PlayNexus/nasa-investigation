"""Unit tests for the EXTRAS site catalogue, taxonomy and systematic pass.

Covers the three things that were silently wrong before:

  * ``metadata`` could not read a PDS value that carried its unit inline, and
    could not associate a browse image with the label the archive actually
    ships, so solar geometry came back empty for every candidate;
  * ``extras_compare`` picked the largest B&W product as the comparison
    reference, which in a real RDR set is the *unrectified* ``*_RED.NOMAP``
    product — the wrong geometry to align everything else to;
  * ``extras_compare`` had no way for a caller to pin the reference, so
    detection coordinates and comparison coordinates could disagree.

Run:  python -m pytest tests/test_extras_pass.py -q
"""

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "pipeline"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import extras_compare  # noqa: E402
import extras_taxonomy as tax  # noqa: E402
import extras_pass  # noqa: E402
import metadata  # noqa: E402
import adjudicate  # noqa: E402


README = """PROJECT NAME
  Corozal_1593E_387S

HIRISE SOURCE IMAGES
 ESP_013948_1410
 ESP_013236_1410

Products are tied to MOLA elevations.
Elevation range for this project:
  VALID_MINIMUM    = -207.69 m
  VALID_MAXIMUM    = 876.60 m

SOCET SET NGATE was used to extract terrain.

Post spacing in DTM is 1 m.

NOTE: Total RMS ==>	   0.11643 px
RMS x	==>	  2.0731 m
RMS y     ==>	0.023656 m
RMS z     ==>      0.86843 m
Mean difference from MOLA 0.085 m, standard deviation 6.486.

KNOWN ARTIFACTS
 - Boxes
	Some DTMs have square areas.
 - CCD seams
	A HiRISE image is made up of 10 individual images.
 - Faceted areas
	Areas that were very bland.
"""


class TestCatalogueMerge(unittest.TestCase):
    """A checkpoint must never shrink the catalogue.

    Checkpoints publish the branch as it stands in the current run, and the
    listing cache means a relaunch re-touches earlier shards in order. Without
    merging, a checkpoint taken minutes into a restart drops every shard it
    has not reached yet, so the on-disk catalogue shrinks instead of growing.
    """

    def _shard(self, name, orbit, fps=1):
        return {
            "name": name, "url": "u", "orbit_from": orbit, "orbit_to": orbit + 99,
            "footprints": [
                {"name": f"{name}_fp{i}", "url": "u", "kind": "observation",
                 "instrument": "ESP", "orbit": orbit, "target": 1,
                 "observations": [], "product_count": 27, "acquire_count": 16,
                 "acquire_bytes": 10_000_000, "products": []}
                for i in range(fps)
            ],
        }

    def _branch(self, shards):
        node = {"name": "RDR/ESP", "product_family": "RDR", "instrument": "ESP",
                "priority": 0, "url": "u", "errors": [], "shards": list(shards)}
        node["shard_count"] = len(shards)
        node["footprint_count"] = sum(len(s["footprints"]) for s in shards)
        node["product_count"] = 27 * node["footprint_count"]
        node["acquire_count"] = 16 * node["footprint_count"]
        node["acquire_bytes"] = 10_000_000 * node["footprint_count"]
        return node

    def test_carries_forward_shards_not_yet_rewalked(self):
        import catalog_extras_site as cat
        old = self._branch([self._shard("ORB_011200_011299", 11200, 19),
                            self._shard("ORB_011300_011399", 11300, 17)])
        new = self._branch([self._shard("ORB_011200_011299", 11200, 19)])
        merged = cat.merge_branch(old, new)
        names = [s["name"] for s in merged["shards"]]
        self.assertEqual(names, ["ORB_011200_011299", "ORB_011300_011399"])
        self.assertEqual(merged["shard_count"], 2)
        self.assertEqual(merged["footprint_count"], 36)

    def test_revisited_shard_takes_the_newer_footprints(self):
        import catalog_extras_site as cat
        old = self._branch([self._shard("ORB_011200_011299", 11200, 3)])
        new = self._branch([self._shard("ORB_011200_011299", 11200, 19)])
        merged = cat.merge_branch(old, new)
        self.assertEqual(merged["shard_count"], 1)
        self.assertEqual(merged["footprint_count"], 19)

    def test_merging_is_never_destructive(self):
        import catalog_extras_site as cat
        big = self._branch([self._shard(f"ORB_{a:06d}_{a+99:06d}", a, 5) for a in range(11200, 11500, 100)])
        for new in (self._branch([]), self._branch([big["shards"][0]])):
            merged = cat.merge_branch(big, new)
            self.assertGreaterEqual(merged["footprint_count"], big["footprint_count"])
            self.assertGreaterEqual(merged["shard_count"], big["shard_count"])

    def test_no_previous_branch_is_a_passthrough(self):
        import catalog_extras_site as cat
        node = self._branch([self._shard("ORB_011200_011299", 11200, 2)])
        self.assertEqual(cat.merge_branch(None, node)["footprint_count"], 2)


class TestAtomicWriteResilience(unittest.TestCase):
    """A transient Windows file lock must not kill a checkpointed crawler.

    `os.replace` raises PermissionError (WinError 5) when any other process
    holds the destination open. A status reader, an indexer or antivirus will
    do that briefly and repeatedly, and a crawl that dies on it loses minutes
    of work for no good reason.
    """

    def test_text_write_retries_a_locked_destination(self):
        import common
        real = os.replace
        state = {"calls": 0}

        def flaky(src, dst):
            state["calls"] += 1
            if state["calls"] < 3:
                raise PermissionError(13, "file is in use by another process")
            return real(src, dst)

        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            os.replace = flaky
            try:
                common.atomic_text_write(target, '{"a":1}')
            finally:
                os.replace = real
            self.assertEqual(state["calls"], 3, "should have retried the locked replace")
            self.assertEqual(json.load(open(target, encoding="utf-8")), {"a": 1})

    def test_csv_write_retries_a_locked_destination(self):
        import common
        real = os.replace
        state = {"calls": 0}

        def flaky(src, dst):
            state["calls"] += 1
            if state["calls"] < 2:
                raise PermissionError(13, "in use")
            return real(src, dst)

        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.csv")
            os.replace = flaky
            try:
                common.atomic_csv_write(target, [{"a": "1"}], ["a"])
            finally:
                os.replace = real
            self.assertEqual(state["calls"], 2)
            with open(target, newline="", encoding="utf-8") as f:
                self.assertEqual(list(csv.DictReader(f)), [{"a": "1"}])

    def test_a_persistent_lock_still_raises_and_leaves_no_litter(self):
        import common

        def always_locked(src, dst):
            raise PermissionError(13, "in use")

        real = os.replace
        with tempfile.TemporaryDirectory() as d:
            target = os.path.join(d, "out.json")
            os.replace = always_locked
            try:
                with self.assertRaises(PermissionError):
                    common.atomic_text_write(target, "x")
            finally:
                os.replace = real
            self.assertFalse(os.path.exists(target))
            self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [],
                             "a failed atomic write must not leave .tmp litter")


class TestSupervisorResilience(unittest.TestCase):
    """The supervisor exists to survive; it must not die of its own bugs."""

    def test_supervise_cannot_see_an_unbound_backoff(self):
        """A plain assignment inside the nested function shadowed `backoff`.

        That read-before-assign raised UnboundLocalError *inside the
        supervision loop*, which took the supervisor down and left both long
        jobs unsupervised — the exact failure the supervisor was added to
        prevent. `nonlocal` is the fix and this guards the regression.
        """
        import run_extras_pipeline as sup
        import inspect
        src = inspect.getsource(sup.main)
        self.assertIn("nonlocal backoff", src)

    def test_main_wraps_supervise_in_a_guard(self):
        import run_extras_pipeline as sup
        import inspect
        src = inspect.getsource(sup.main)
        self.assertIn("except Exception as e", src.split("supervise(j)")[1][:400],
                      "the supervise() call must sit inside a try/except")


class TestSupervisor(unittest.TestCase):
    """The supervisor's whole job is telling "working" from "wedged"."""

    def test_catalogue_progress_counts_shards_and_footprints(self):
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "extras_site.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"branches": [
                    {"shards": [{"name": "a"}, {"name": "b"}], "footprint_count": 7},
                    {"shards": [{"name": "c"}], "footprint_count": 3},
                ]}, f)
            shards, footprints, age = sup.catalogue_progress(p)
            self.assertEqual((shards, footprints), (3, 10))
            self.assertLess(age, 60)
            # missing file must not look like progress
            self.assertEqual(sup.catalogue_progress(os.path.join(d, "nope.json"))[0], 0)

    def test_pass_progress_reads_state(self):
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
                json.dump({"processed": 42}, f)
            n, age = sup.pass_progress(d)
            self.assertEqual(n, 42)
            self.assertLess(age, 60)
            self.assertEqual(sup.pass_progress(os.path.join(d, "nope"))[0], 0)

    def test_corrupt_progress_file_is_not_a_crash(self):
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as f:
                f.write("{ not json")
            self.assertEqual(sup.pass_progress(d)[0], 0)
            with open(os.path.join(d, "cat.json"), "w", encoding="utf-8") as f:
                f.write("{ not json")
            self.assertEqual(sup.catalogue_progress(os.path.join(d, "cat.json"))[0], 0)

    def test_build_jobs_probes_get_the_path_not_the_flag(self):
        """`--catalogue` is a bool; os.path.exists(True) stats file descriptor 1.

        Passing the flag where the path belongs made the stall check inspect
        the supervisor's own stdout, so it never saw the catalogue advance and
        never detected a real stall.
        """
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            cat = os.path.join(d, "cat.json")
            with open(cat, "w", encoding="utf-8") as f:
                json.dump({"branches": [{"shards": [{"n": 1}], "footprint_count": 5}]}, f)
            args = sup.main.__globals__["argparse"].Namespace(
                catalogue=True, pass_=False, both=False, status=False,
                catalogue_path=cat, out=os.path.join(d, "pass"), log=os.path.join(d, "l.log"),
                branches="", scales="core", geometries="map", limit=0,
                crawl_workers=6, pass_file_workers=2, disk_floor_gb=100.0,
                checkpoint_seconds=240.0, catalogue_stall=3600.0, pass_stall=1800.0,
                wake_cooldown=180.0,
            )
            jobs = sup.build_jobs(args)
            self.assertEqual(len(jobs), 1)
            value, age = jobs[0].progress()
            self.assertEqual(value, 5)
            self.assertLess(age, 60)

    def test_finished_job_can_be_woken_by_new_work(self):
        """The pass drains its queue long before the crawl finishes.

        Without a wake condition the supervisor would treat the first drain as
        the end of the run, and no image catalogued after it would ever be
        picked up — which is every image, for the hours the crawl runs.
        """
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "s.log")
            seen = {"value": 10}
            job = sup.Job(
                "pass", [sys.executable, "-c", "pass"],
                probe=lambda: (0, 0.0), stall_seconds=1e9, log_path=log,
                wake=lambda: seen["value"] > 10, wake_cooldown=0.0,
            )
            job.start()
            job.proc.wait()
            job.finished = True
            job._wake_seen = seen["value"]
            self.assertFalse(job.wake(), "no growth yet -> stay finished")
            seen["value"] = 25
            self.assertTrue(job.wake(), "catalogue grew -> wake the pass")

    def test_wake_is_none_means_never_restart(self):
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            job = sup.Job("x", [sys.executable, "-c", "pass"],
                          probe=lambda: (0, 0.0), stall_seconds=1e9,
                          log_path=os.path.join(d, "s.log"))
            self.assertIsNone(job.wake)
            self.assertFalse(job.wake)

    def test_probe_contract_is_a_two_tuple(self):
        """supervise() unpacks (value, age); the probe must match."""
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "extras_site.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"branches": [
                    {"shards": [{"name": "a"}], "footprint_count": 4}]}, f)
            value, age = sup.catalogue_probe(p)
            self.assertEqual(value, 4)
            self.assertLess(age, 60)

    def test_job_restarts_on_nonzero_exit_and_stops_on_zero(self):
        """A clean exit is final; a crash is retried.

        Both jobs exit 0 when they are genuinely finished, or when a budget
        such as --disk-floor-gb stops them, so relaunching on rc=0 would spin.
        """
        import run_extras_pipeline as sup
        with tempfile.TemporaryDirectory() as d:
            log = os.path.join(d, "s.log")
            probe = lambda: (0, 0.0)  # noqa: E731
            # a job that always fails is retried, not declared done
            failing = sup.Job("boom", [sys.executable, "-c", "raise SystemExit(3)"],
                              probe, 1e9, log)
            failing.start()
            failing.proc.wait()
            self.assertFalse(failing.alive())
            self.assertEqual(failing.proc.returncode, 3)
            self.assertFalse(failing.finished, "a crash must not mark the job finished")
            # a job that succeeds is finished and must not be relaunched
            ok = sup.Job("fine", [sys.executable, "-c", "pass"], probe, 1e9, log)
            ok.start()
            ok.proc.wait()
            self.assertEqual(ok.proc.returncode, 0)
            ok.finished = True
            self.assertTrue(ok.finished)
            self.assertTrue(os.path.exists(log))


class TestThroughputAccounting(unittest.TestCase):
    """The ETA must not be flattered by a reprocess sweep.

    A --force run re-adjudicates already-fetched images, skipping the ~40 s
    download, so a lifetime average can report >100 images/min while a fresh
    image genuinely takes that long. The estimate is based on a short trailing
    window instead, with download and analysis time reported separately.
    """

    def test_window_is_bounded(self):
        st = {"recent": []}
        for i in range(200):
            extras_pass.note_timing(st, 40.0, 35.0)
        self.assertEqual(len(st["recent"]), extras_pass.RATE_WINDOW)

    def test_eta_uses_the_window_not_the_lifetime(self):
        state = {"processed": 1000, "elapsed_s": 600.0, "recent": [],
                 "download_s": 0.0, "analysis_s": 0.0}
        # 20 genuinely fresh images at 40 s each -> 2.0 img/min, not 100/min
        for _ in range(20):
            extras_pass.note_timing(state, 40.0, 35.0)
        with tempfile.TemporaryDirectory() as d:
            extras_pass.save_state(os.path.join(d, "s.json"), state, 2000, d)
            out = json.load(open(os.path.join(d, "s.json"), encoding="utf-8"))
        self.assertAlmostEqual(out["sec_per_image"], 40.0, places=1)
        self.assertAlmostEqual(out["images_per_min"], 1.5, places=1)  # 20/800*60
        self.assertAlmostEqual(out["download_share_pct"], 87.5, places=1)
        # the lifetime average is still reported, but separately
        self.assertAlmostEqual(out["lifetime_images_per_min"], 100.0, places=1)
        self.assertEqual(out["window_images"], 20)

    def test_reported_state_stays_small(self):
        state = {"processed": 10, "elapsed_s": 1.0, "recent": [],
                 "download_s": 0.0, "analysis_s": 0.0}
        for i in range(500):
            extras_pass.note_timing(state, 1.0, 0.5)
        with tempfile.TemporaryDirectory() as d:
            extras_pass.save_state(os.path.join(d, "s.json"), state, 100, d)
            size = os.path.getsize(os.path.join(d, "s.json"))
        self.assertLess(size, 20_000, "progress state must not grow with images processed")


class TestParentGeometryJoin(unittest.TestCase):
    """A stereo pair has no lighting of its own; its source RDR observation has it.

    The DTM README documents the grid, the RMS and the elevation range but
    nothing about the sun. The lighting belongs to the RDR observation the DTM
    was built from, which lives in a different footprint directory and a
    different branch.
    """

    def _parent_tree(self, root, obs, instrument="ESP"):
        d = os.path.join(root, "RDR", instrument, obs)
        os.makedirs(d, exist_ok=True)
        fields = ["name", "observation_id", "incidence_angle", "solar_azimuth",
                  "solar_elevation", "pixel_scale_m"]
        with open(os.path.join(d, "catalog.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerow({"name": f"{obs}_MIRB.browse.jpg", "observation_id": obs,
                        "incidence_angle": "57.508291", "solar_azimuth": "171.160759",
                        "solar_elevation": "32.491709", "pixel_scale_m": "0.5"})

    def test_borrows_lighting_from_the_source_observation(self):
        with tempfile.TemporaryDirectory() as d:
            self._parent_tree(d, "ESP_013948_1410")
            geom, missing = extras_pass.parent_solar_geometry(d, ["ESP_013948_1410"])
            self.assertEqual(missing, [])
            self.assertAlmostEqual(float(geom["incidence_angle"]), 57.508291, places=4)
            self.assertAlmostEqual(float(geom["solar_azimuth"]), 171.160759, places=3)
            self.assertEqual(geom["geometry_source"], "parent RDR observation")

    def test_reports_parents_it_cannot_find(self):
        with tempfile.TemporaryDirectory() as d:
            geom, missing = extras_pass.parent_solar_geometry(d, ["ESP_999999_9999"])
            self.assertEqual(geom, {})
            self.assertEqual(missing, ["ESP_999999_9999"])

    def test_apply_parent_geometry_never_overwrites_dtm_post_spacing(self):
        """The DTM grid (1 m post) is not the parent's browse grid (0.5 m)."""
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "incidence_angle", "solar_azimuth", "pixel_scale_m"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"name": "DTEEC_A01.ab.jpg", "incidence_angle": "",
                            "solar_azimuth": "", "pixel_scale_m": "1.0"})
                w.writerow({"name": "ESP_1_RED_C_01_ORTHO.br.jpg", "incidence_angle": "",
                            "solar_azimuth": "", "pixel_scale_m": "1.0"})
            n = extras_pass.apply_parent_geometry(csv_path, {
                "incidence_angle": "57.508291", "solar_azimuth": "171.160759",
                "pixel_scale_m": "0.5", "observation_id": "ESP_1"})
            self.assertGreater(n, 0)
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            for name, row in rows.items():
                self.assertAlmostEqual(float(row["incidence_angle"]), 57.508291, places=4)
                self.assertEqual(row["pixel_scale_m"], "1.0", f"{name} lost its DTM post spacing")

    def test_instrument_routes_to_the_right_rdr_branch(self):
        with tempfile.TemporaryDirectory() as d:
            self._parent_tree(d, "PSP_001336_1560", instrument="PSP")
            geom, missing = extras_pass.parent_solar_geometry(d, ["PSP_001336_1560"])
            self.assertEqual(missing, [])
            self.assertIn("incidence_angle", geom)


class TestDtmReadmeGeometry(unittest.TestCase):
    """Stereo pairs ship no per-image label; the README is the only source.

    The post spacing is the ground sample distance of every DTM derivative and
    of the orthorectified image beside it, and it appears nowhere else — the
    letter in `..._A01` / `..._U01` is the producing *institution*
    (A = Arizona, U = USGS), not the grid spacing, which the README's own
    naming-convention section invites you to misread.
    """

    def _parse(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "README.TXT")
            with open(p, "w", encoding="utf-8") as f:
                f.write(README)
            return metadata.parse_dtm_readme(p)

    def test_post_spacing_and_valid_range(self):
        g = self._parse()
        self.assertEqual(g["dtm_post_spacing_m"], 1.0)
        self.assertAlmostEqual(g["dtm_valid_min_m"], -207.69, places=2)
        self.assertAlmostEqual(g["dtm_valid_max_m"], 876.60, places=2)

    def test_stereo_rms(self):
        g = self._parse()
        self.assertAlmostEqual(g["dtm_rms_total_px"], 0.11643, places=5)
        self.assertAlmostEqual(g["dtm_rms_x_m"], 2.0731, places=4)
        self.assertAlmostEqual(g["dtm_rms_y_m"], 0.023656, places=5)
        self.assertAlmostEqual(g["dtm_rms_z_m"], 0.86843, places=5)

    def test_mola_difference_and_stdev_are_distinct(self):
        """The stdev is a second capture group; reading group 1 returns the mean."""
        g = self._parse()
        self.assertAlmostEqual(g["dtm_mola_mean_diff_m"], 0.085, places=3)
        self.assertAlmostEqual(g["dtm_mola_stdev_m"], 6.486, places=3)

    def test_lat_lon_hemispheres(self):
        """Project codes are <lon*10><E|W>_<lat*10><N|S> — longitude first."""
        g = self._parse()
        self.assertAlmostEqual(g["dtm_longitude"], 159.3, places=1)
        self.assertAlmostEqual(g["dtm_latitude"], -38.7, places=1)

    def test_source_images_and_software(self):
        g = self._parse()
        self.assertEqual(g["dtm_source_images"], ["ESP_013948_1410", "ESP_013236_1410"])
        self.assertIn("NGATE", g["dtm_software"])

    def test_known_artifacts_are_surfaced(self):
        """These are terrain-model defects, not surface features."""
        g = self._parse()
        self.assertEqual(g["dtm_known_artifacts"], ["boxes", "ccd_seams", "faceted_areas"])

    def test_geometry_from_path_supplies_scale_for_dtm_and_ortho(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "README.TXT"), "w", encoding="utf-8") as f:
                f.write(README)
            for name in ("DTEEC_013948_1410_013236_1410_A01.ab.jpg",
                         "ESP_013948_1410_RED_C_01_ORTHO.br.jpg"):
                with self.subTest(name=name):
                    g = metadata.geometry_from_path(os.path.join(d, name))
                    self.assertEqual(g["pixel_scale_m"], 1.0)
                    self.assertEqual(g["pixel_scale_source"], "DTM README post spacing")
                    self.assertAlmostEqual(g["dtm_rms_z_m"], 0.86843, places=5)

    def test_empty_or_missing_readme_is_harmless(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "README.TXT")
            open(p, "w", encoding="utf-8").close()
            self.assertEqual(metadata.parse_dtm_readme(p), {})
            self.assertEqual(metadata.parse_dtm_readme(os.path.join(d, "nope.TXT")), {})


class TestCrossVariantPersistence(unittest.TestCase):
    """The cross-rendering evidence has to be able to change a verdict.

    With reference-only detection there is exactly one *detection* image per
    footprint, so `cross_band_agreement` has no siblings to compare and every
    candidate came back agrees=0/disagrees=0 — no verdict could ever reach
    CONFIRMED-LEAD, and none could be refuted either. The persistence map
    extras_compare already computes is the independent evidence.
    """

    def _report(self, per_variant):
        return {"candidate_persistence": per_variant}

    def test_persistence_key_matches_extras_compare_format(self):
        self.assertEqual(adjudicate.persistence_key("ESP_1_RED.browse.jpg", 10, 20, 30, 40),
                         "ESP_1_RED.browse.jpg|10,20@30x40")

    def test_load_persistence_flattens_the_nested_report(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "compare_report.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._report({
                    "ESP_1_MIRB.browse.jpg": {"ESP_1_RED.browse.jpg|10,20@30x40": 0.95},
                }), f)
            got = adjudicate.load_persistence(path)
            self.assertEqual(
                got["ESP_1_RED.browse.jpg|10,20@30x40"]["ESP_1_MIRB.browse.jpg"], 0.95)
            self.assertEqual(adjudicate.load_persistence(""), {})

    def test_hold_collapse_and_nomap_is_ignored(self):
        # a real surface feature holds its contrast in filtered colour
        med, hold, collapse, n = adjudicate.summarise_persistence(
            {"ESP_1_MIRB.browse.jpg": 0.92, "ESP_1_MRGB.browse.jpg": 1.05})
        self.assertGreaterEqual(med, 0.92)
        self.assertEqual((hold, collapse, n), (2, 0, 2))

        # a reference-rendering artifact collapses everywhere
        _med, hold, collapse, n = adjudicate.summarise_persistence(
            {"ESP_1_MIRB.browse.jpg": 0.10, "ESP_1_MRGB.browse.jpg": 0.05})
        self.assertEqual((hold, collapse, n), (0, 2, 2))

        # detector geometry is not evidence about the surface, so it is
        # excluded: a low ratio there must not manufacture a collapse
        _med, hold, collapse, n = adjudicate.summarise_persistence(
            {"ESP_1_MIRB.browse.jpg": 0.95, "ESP_1_RED.NOMAP.browse.jpg": 0.02})
        self.assertEqual((hold, collapse, n), (1, 0, 1))

        # thumbnails are downsamples of renderings already tested
        _med, _h, _c, n = adjudicate.summarise_persistence(
            {"ESP_1_MIRB.browse.jpg": 0.9, "ESP_1_MIRB.thumb.jpg": 0.01})
        self.assertEqual(n, 1)

    def test_verdict_refutes_a_reference_only_artifact(self):
        """Present in B&W, absent everywhere else -> BAND-DEPENDENT."""
        self.assertEqual(
            adjudicate.verdict(80.0, 2, agrees=0, compactness=0.9, aspect=1.0,
                               flags="", area_px=500, xv_collapse=3, xv_tested=3),
            "BAND-DEPENDENT")

    def test_verdict_confirms_a_cross_rendering_hold(self):
        """Holds in a sibling rendering, discrete, plausible size -> CONFIRMED."""
        self.assertEqual(
            adjudicate.verdict(80.0, 2, agrees=2, compactness=0.9, aspect=1.0,
                               flags="", area_px=500, xv_collapse=0, xv_tested=2,
                               contrast=2.3),
            "CONFIRMED-LEAD")
        # but a streaky, non-discrete one is terrain, not a lead
        self.assertEqual(
            adjudicate.verdict(80.0, 2, agrees=2, compactness=0.1, aspect=5.0,
                               flags="", area_px=500, xv_collapse=0, xv_tested=2,
                               contrast=2.3),
            "TERRAIN")

    def test_persistence_alone_never_makes_a_lead(self):
        """Holding across renderings is the *expected* result for real terrain.

        docs/EXTRAS.md section 6: a feature that survives B&W -> colour ->
        ortho -> DTM-shaded *is terrain*. So a persistent but faint blob must
        land on TERRAIN, not be promoted to a lead on the strength of having
        been confirmed as ordinary.
        """
        for faint in (0.41, 1.15, 1.29, 1.49):
            with self.subTest(contrast=faint):
                self.assertEqual(
                    adjudicate.verdict(80.0, 2, agrees=2, compactness=1.0, aspect=1.0,
                                       flags="", area_px=500, xv_collapse=0, xv_tested=3,
                                       contrast=faint, contrast_bar=1.5),
                    "TERRAIN")
        # at or above the bar the same geometry is a lead
        self.assertEqual(
            adjudicate.verdict(80.0, 2, agrees=2, compactness=1.0, aspect=1.0,
                               flags="", area_px=500, xv_collapse=0, xv_tested=3,
                               contrast=2.3, contrast_bar=1.5),
            "CONFIRMED-LEAD")

    def test_band_dependent_needs_actual_evidence(self):
        """A single tested variant cannot establish a collapse."""
        self.assertNotEqual(
            adjudicate.verdict(80.0, 2, agrees=0, compactness=0.9, aspect=1.0,
                               flags="", area_px=500, xv_collapse=1, xv_tested=1),
            "BAND-DEPENDENT")

    def test_evidence_class_one_still_wins(self):
        self.assertEqual(
            adjudicate.verdict(90.0, 1, agrees=2, compactness=0.9, aspect=1.0,
                               flags="", area_px=500, xv_collapse=0, xv_tested=2),
            "EXPLAINED-ARTIFACT")

    def test_persistence_map_is_not_silently_capped(self):
        """Every detected box must reach the adjudicator, not the first 50.

        A hard cap at 50 boxes per variant used to discard half the
        cross-variant evidence on a busy footprint, in arbitrary dict order,
        and the missing boxes were indistinguishable from "no evidence".
        """
        self.assertGreaterEqual(extras_compare.PERSISTENCE_BOX_CAP, 500)
        with tempfile.TemporaryDirectory() as d:
            import numpy as np
            from PIL import Image
            # a clean 64x64 terrain with one clear bright square
            base = np.full((64, 64), 100, dtype=np.uint8)
            base[24:40, 24:40] = 200
            Image.fromarray(base).save(os.path.join(d, "ESP_1_RED.browse.jpg"))
            Image.fromarray(base).save(os.path.join(d, "ESP_1_MIRB.browse.jpg"))
            # 150 candidate boxes, all inside the bright square
            cands = [{"image": "ESP_1_RED.browse.jpg", "path": "x",
                      "x": 26 + (i % 7), "y": 26 + (i // 20), "w": 3, "h": 3}
                     for i in range(150)]
            rep = extras_compare.compare_footprint(
                __import__("pathlib").Path(d), cands, __import__("pathlib").Path(d) / "out",
                diff_format="none")
            got = rep.get("candidate_persistence", {})
            self.assertNotIn("candidate_persistence_truncated", rep)
            for variant, boxes in got.items():
                self.assertEqual(len(boxes), 150,
                                 f"{variant} kept {len(boxes)} of 150 boxes")

    def test_recommend_mentions_the_rendering(self):
        self.assertIn("rendering", adjudicate.recommend("BAND-DEPENDENT"))


class TestExtrasTaxonomy(unittest.TestCase):
    """Every real EXTRAS filename maps to the right product class and role."""

    def test_rdr_browse_set(self):
        cases = {
            "ESP_011261_1960_RED.browse.jpg": ("red", "rdr_browse", "browse", "map"),
            "ESP_011261_1960_RED.abrowse.jpg": ("red", "rdr_browse", "abrowse", "map"),
            "ESP_011261_1960_RED.thumb.jpg": ("red", "rdr_browse", "thumb", "map"),
            "ESP_011261_1960_RED.NOMAP.browse.jpg": ("red", "rdr_browse", "browse", "nomap"),
            "ESP_011261_1960_MIRB.browse.jpg": ("color", "rdr_browse", "browse", "map"),
            "ESP_011261_1960_MRGB.browse.jpg": ("color", "rdr_browse", "browse", "map"),
            "ESP_011261_1960_IRB.NOMAP.browse.jpg": ("color", "rdr_browse", "browse", "nomap"),
            "ESP_011261_1960_COLOR.QLOOK.JP2": ("color", "rdr_fullres", "fullres", "quicklook"),
            "ESP_011261_1960_MIRB.LBL": ("other", "rdr_label", "", "map"),
            "PSP_001330_1395_RED.browse.jpg": ("red", "rdr_browse", "browse", "map"),
            "AEB_000001_0000_RED.browse.jpg": ("red", "rdr_browse", "browse", "map"),
        }
        for name, (role, cls, scale, geom) in cases.items():
            with self.subTest(name=name):
                info = tax.classify_file(name, "RDR/ESP")
                self.assertEqual((info["role"], info["product_class"], info["scale"], info["geometry"]),
                                 (role, cls, scale, geom))

    def test_dtm_and_ortho(self):
        cases = {
            "DTEEC_011265_1560_011331_1560_U01.ab.jpg": ("dtm", "dtm_derivative", "browse", "dtm"),
            "DTEEC_011265_1560_011331_1560_U01.th.jpg": ("dtm", "dtm_derivative", "thumbnail", "dtm"),
            "DTEEC_013948_1410_013236_1410_A01.JP2": ("dtm", "dtm_elevation", "fullres", "dtm"),
            "DTFEC_013948_1410_013236_1410_A01.JP2": ("fom", "fom_map", "fullres", "dtm"),
            "ESP_011265_1560_RED_C_01_ORTHO.br.jpg": ("ortho_red", "ortho_browse", "browse", "ortho"),
            "ESP_011331_1560_RED_C_01_ORTHO.th.jpg": ("ortho_red", "ortho_browse", "thumbnail", "ortho"),
            "ESP_013948_1410_IRB_C_01_ORTHO.br.jpg": ("ortho_color", "ortho_browse", "browse", "ortho"),
            "FOM_MAP_LEGEND.JPG": ("fom", "fom_legend", "browse", "dtm"),
            "README.TXT": ("other", "readme", "", ""),
        }
        for name, (role, cls, scale, geom) in cases.items():
            with self.subTest(name=name):
                info = tax.classify_file(name, "DTM/ESP")
                self.assertEqual((info["role"], info["product_class"], info["scale"], info["geometry"]),
                                 (role, cls, scale, geom))

    def test_anaglyph_and_legacy_edr(self):
        anag = tax.classify_file("ESP_011310_1395_ESP_011811_1395_RED.browse.png", "ANAGLYPH/ESP")
        self.assertEqual((anag["role"], anag["product_class"], anag["geometry"]), ("anaglyph", "anaglyph_browse", "anaglyph"))
        for name, role in (("ESP_011261_1960_RED0_0.browse.jpg", "red"),
                           ("ESP_011261_1960_IR10_1.browse.jpg", "color"),
                           ("ESP_011261_1960_BG13_0.browse.jpg", "color")):
            with self.subTest(name=name):
                info = tax.classify_file(name, "EDR/ESP")
                self.assertEqual(info["product_class"], "edr_browse")
                self.assertEqual(info["role"], role)

    def test_browse_only_policy_refuses_jp2(self):
        jp2 = tax.classify_file("ESP_011261_1960_MIRB.JP2", "RDR/ESP")
        fetch, _ = tax.acquire_decision(jp2, 0.0)
        self.assertFalse(fetch)
        jpg = tax.classify_file("ESP_011261_1960_MIRB.browse.jpg", "RDR/ESP")
        self.assertTrue(tax.acquire_decision(jpg, 0.0)[0])
        # with a budget the JP2 becomes eligible again
        self.assertTrue(tax.acquire_decision(jp2, 400.0)[0])

    def test_scale_set_controls_abrowse(self):
        """`core` = full browse + thumbnail; `full` adds the binned abrowse."""
        abrowse = tax.classify_file("ESP_011261_1960_RED.abrowse.jpg", "RDR/ESP")
        browse = tax.classify_file("ESP_011261_1960_RED.browse.jpg", "RDR/ESP")
        thumb = tax.classify_file("ESP_011261_1960_RED.thumb.jpg", "RDR/ESP")
        core = tax.SCALE_SETS["core"]
        full = tax.SCALE_SETS["full"]
        self.assertEqual(set(core), {"browse", "thumb"})
        self.assertTrue(tax.acquire_decision(browse, 0.0, core)[0])
        self.assertTrue(tax.acquire_decision(thumb, 0.0, core)[0])
        # the half-res duplicate costs nearly as much as the browse and adds
        # no coverage, so the default policy leaves it out
        fetch, reason = tax.acquire_decision(abrowse, 0.0, core)
        self.assertFalse(fetch)
        self.assertIn("abrowse", reason)
        self.assertTrue(tax.acquire_decision(abrowse, 0.0, full)[0])

    def test_footprint_classification(self):
        obs = tax.classify_footprint("ESP_011261_1960")
        self.assertEqual(obs["kind"], "observation")
        self.assertEqual(obs["observations"], ["ESP_011261_1960"])
        self.assertEqual(obs["orbit"], 11261)
        pair = tax.classify_footprint("ESP_011265_1560_ESP_011331_1560")
        self.assertEqual(pair["kind"], "stereo_pair")
        self.assertEqual(pair["observations"], ["ESP_011265_1560", "ESP_011331_1560"])

    def test_geometry_set_drops_detector_geometry(self):
        """NOMAP/quicklook are the biggest files and add coverage, not morphology."""
        nomap = tax.classify_file("ESP_011261_1960_RED.NOMAP.browse.jpg", "RDR/ESP")
        mapped = tax.classify_file("ESP_011261_1960_RED.browse.jpg", "RDR/ESP")
        quicklook = tax.classify_file("ESP_011261_1960_RED.QLOOK.JP2", "RDR/ESP")
        core = tax.SCALE_SETS["core"]

        # default policy: map-projected kept, detector geometry dropped
        self.assertTrue(tax.acquire_decision(mapped, 0.0, core, tax.GEOMETRY_SETS["map"])[0])
        fetch, reason = tax.acquire_decision(nomap, 0.0, core, tax.GEOMETRY_SETS["map"])
        self.assertFalse(fetch)
        self.assertIn("nomap", reason)

        # opting back in restores the complete variant set
        self.assertTrue(tax.acquire_decision(nomap, 0.0, core, tax.GEOMETRY_SETS["all"])[0])
        self.assertFalse(tax.acquire_decision(quicklook, 0.0, core, tax.GEOMETRY_SETS["all"])[0])

    def test_geometry_set_keeps_ortho_and_dtm(self):
        """The documented debunk path is RED -> colour -> ortho -> DTM-shaded."""
        geom_map = tax.GEOMETRY_SETS["map"]
        cases = (
            ("DTEEC_011265_1560_011331_1560_U01.ab.jpg", "DTM/ESP", True),
            ("ESP_011265_1560_RED_C_01_ORTHO.br.jpg", "DTM/ESP", True),
            ("ESP_011310_1395_ESP_011811_1395_RED.browse.png", "ANAGLYPH/ESP", True),
            ("ESP_011261_1960_MIRB.browse.jpg", "RDR/ESP", True),
        )
        core = tax.SCALE_SETS["core"]
        for name, branch, want in cases:
            with self.subTest(name=name):
                got = tax.acquire_decision(tax.classify_file(name, branch), 0.0, core, geom_map)[0]
                self.assertEqual(got, want)

    def test_reference_choice_prefers_map_projected_red(self):
        entries = [
            dict(tax.classify_file(n, "RDR/ESP"), name=n, bytes=b)
            for n, b in (
                # the NOMAP product is the largest B&W file, as in a real RDR set
                ("ESP_011261_1960_RED.NOMAP.browse.jpg", 7_424_568),
                ("ESP_011261_1960_RED.browse.jpg", 2_779_311),
                ("ESP_011261_1960_RED.abrowse.jpg", 2_646_385),
                ("ESP_011261_1960_RED.thumb.jpg", 201_708),
                ("ESP_011261_1960_MIRB.browse.jpg", 3_242_028),
            )
        ]
        self.assertEqual(tax.reference_choice(entries), "ESP_011261_1960_RED.browse.jpg")

    def test_reference_choice_none_without_bandw(self):
        entries = [dict(tax.classify_file("ESP_011310_1395_ESP_011811_1395_RED.browse.png", "ANAGLYPH/ESP"),
                        name="a.png", bytes=1)]
        self.assertIsNone(tax.reference_choice(entries))


class TestReferenceSelection(unittest.TestCase):
    """extras_compare must align to the map-projected B&W RED browse."""

    def _siblings(self, tmp, real=False):
        names = (
            "ESP_011261_1960_RED.browse.jpg",
            "ESP_011261_1960_RED.NOMAP.browse.jpg",   # deliberately the largest
            "ESP_011261_1960_MIRB.browse.jpg",
        )
        for n in names:
            p = tmp / n
            if real:
                from PIL import Image
                import numpy as np
                # same terrain, one rendered in colour, so the diff is real
                arr = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
                img = arr if "MIRB" not in n else np.stack([arr, arr // 2, arr // 3], axis=-1)
                Image.fromarray(img).save(p)
            else:
                p.write_bytes(b"x")
        return sorted(tmp.iterdir())

    def test_choose_reference_rejects_nomap(self):
        with tempfile.TemporaryDirectory() as d:
            sibs = self._siblings(Path(d))
            self.assertEqual(extras_compare.choose_reference(sibs).name,
                             "ESP_011261_1960_RED.browse.jpg")

    def test_reference_rank_orders_geometry_before_size(self):
        with tempfile.TemporaryDirectory() as d:
            sibs = {p.name: p for p in self._siblings(Path(d))}
            ranks = {n: extras_compare._reference_rank(p) for n, p in sibs.items()}
            self.assertLess(ranks["ESP_011261_1960_RED.browse.jpg"],
                            ranks["ESP_011261_1960_RED.NOMAP.browse.jpg"])

    def test_compare_footprint_honours_pinned_reference(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            self._siblings(tmp, real=True)
            out = Path(d) / "out"
            rep = extras_compare.compare_footprint(tmp, [], out, reference="ESP_011261_1960_MIRB.browse.jpg")
            self.assertEqual(rep.get("reference"), "ESP_011261_1960_MIRB.browse.jpg")
            # without pinning it falls back to the map-projected RED browse
            rep2 = extras_compare.compare_footprint(tmp, [], out)
            self.assertEqual(rep2.get("reference"), "ESP_011261_1960_RED.browse.jpg")

    def test_color_and_rgb_get_color_role(self):
        self.assertEqual(extras_compare._variant_role("ESP_011261_1960_COLOR.browse.jpg"), "color")
        self.assertEqual(extras_compare._variant_role("ESP_011261_1960_RGB.NOMAP.browse.jpg"), "color")
        self.assertEqual(extras_compare._variant_role("ESP_011261_1960_MRGB.browse.jpg"), "color")
        # MRGB must not be mistaken for RGB-only, and RED stays the reference
        self.assertEqual(extras_compare._variant_role("ESP_011261_1960_RED.browse.jpg"), "red")
        self.assertIn("COLOR", extras_compare._taxonomy("ESP_011261_1960_COLOR.browse.jpg"))


class TestMetadataGeometry(unittest.TestCase):
    """Solar geometry is the primary debunk signal; it must actually parse."""

    LABEL = """PDS_VERSION_ID = PDS3
OBSERVATION_ID            = "ESP_011261_1960"
PRODUCT_ID                = "ESP_011261_1960_MIRB"
INSTRUMENT_ID             = "HIRISE"
TARGET_NAME               = "MARS"
A_AXIS_RADIUS                = 3394.8398133163 <KM>
MAP_RESOLUTION               = 118502.26464032 <PIX/DEG>
MAP_SCALE = 0.5 <METERS/PIXEL>
INCIDENCE_ANGLE   = 57.508291 <DEG>
EMISSION_ANGLE    = 0.305223 <DEG>
PHASE_ANGLE       = 57.312488 <DEG>
SUB_SOLAR_AZIMUTH = 171.160759 <DEG>
END
"""

    def test_num_strips_inline_units(self):
        self.assertAlmostEqual(metadata._num("57.508291 <DEG>"), 57.508291, places=5)
        self.assertAlmostEqual(metadata._num("0.5 <METERS/PIXEL>"), 0.5)
        self.assertAlmostEqual(metadata._num("1,234.5"), 1234.5)
        self.assertIsNone(metadata._num("NOT_APPLICABLE_CONSTANT"))
        self.assertIsNone(metadata._num(""))
        self.assertIsNone(metadata._num(None))

    def test_geometry_from_hirise_label(self):
        g = metadata.geometry_from_label(self.LABEL)
        self.assertEqual(g["observation_id"], "ESP_011261_1960")
        self.assertAlmostEqual(g["incidence_angle"], 57.508291, places=5)
        self.assertAlmostEqual(g["solar_azimuth"], 171.160759, places=4)
        self.assertAlmostEqual(g["solar_elevation"], 90.0 - 57.508291, places=5)
        # MAP_SCALE is the HiRISE map-projected pixel size
        self.assertAlmostEqual(g["pixel_scale_m"], 0.5)

    def test_pixel_scale_from_map_resolution_when_no_map_scale(self):
        text = self.LABEL.replace("MAP_SCALE = 0.5 <METERS/PIXEL>\n", "")
        g = metadata.geometry_from_label(text)
        expected = (3.141592653589793 / 180.0) * (3394.8398133163 * 1000.0) / 118502.26464032
        self.assertAlmostEqual(g["pixel_scale_m"], expected, places=6)

    def test_find_label_strips_render_scale_token(self):
        with tempfile.TemporaryDirectory() as d:
            # the archive ships MIRB.LBL, not MIRB.browse.LBL
            (Path(d) / "ESP_011261_1960_MIRB.LBL").write_text(self.LABEL, encoding="utf-8")
            for img in ("ESP_011261_1960_MIRB.browse.jpg", "ESP_011261_1960_MIRB.thumb.jpg"):
                with self.subTest(img=img):
                    lbl = metadata._find_label(os.path.join(d, img))
                    self.assertIsNotNone(lbl, f"{img} should resolve to the sibling label")
                    self.assertTrue(lbl.endswith("MIRB.LBL"))
                    g = metadata.geometry_from_path(os.path.join(d, img))
                    self.assertIsNotNone(g["incidence_angle"])


class TestPassQueue(unittest.TestCase):
    """The pass must visit every footprint in one stable, reproducible order."""

    def _catalogue(self):
        def fp(name, orbit, products):
            return {"name": name, "url": f"u/{name}/", "kind": "observation", "orbit": orbit,
                    "target": 1, "observations": [name], "product_count": len(products),
                    "acquire_count": sum(1 for p in products if p["acquire"]),
                    "acquire_bytes": sum(p["bytes"] for p in products if p["acquire"]),
                    "reference": None, "products": products}

        def prod(n, bytes_, acquire=True):
            return {"name": n, "url": f"u/{n}", "bytes": bytes_, "acquire": acquire, "scale": "browse"}

        return {
            "branches": [
                {"name": "EDR/ESP", "priority": 9, "product_family": "EDR", "instrument": "ESP", "shards": [
                    {"name": "ORB_011200_011299", "orbit_from": 11200,
                     "footprints": [fp("ESP_011900_1000", 11900, [prod("a.jpg", 10)])]}]},
                {"name": "DTM/ESP", "priority": 1, "product_family": "DTM", "instrument": "ESP", "shards": [
                    {"name": "ORB_011300_011399", "orbit_from": 11300,
                     "footprints": [fp("ESP_011350_1560_ESP_011400_1560", 11350, [prod("b.jpg", 10)])]}]},
                {"name": "RDR/ESP", "priority": 0, "product_family": "RDR", "instrument": "ESP", "shards": [
                    {"name": "ORB_011300_011399", "orbit_from": 11300, "footprints": [
                        fp("ESP_011380_1200", 11380, [prod("c.jpg", 10)]),
                        fp("ESP_011310_1200", 11310, [prod("d.jpg", 10)]),
                        # every product skipped -> must not be queued at all
                        fp("ESP_011320_1200", 11320, [prod("e.jp2", 10, acquire=False)]),
                    ]}]},
            ]
        }

    def test_queue_is_ordered_and_filtered(self):
        q = extras_pass.iter_queue(self._catalogue())
        self.assertEqual(
            [it["name"] for it in q],
            ["ESP_011310_1200", "ESP_011380_1200", "ESP_011350_1560_ESP_011400_1560", "ESP_011900_1000"],
        )
        # RDR/ESP first (priority 0), DTM/ESP second, legacy EDR last
        self.assertEqual([it["branch"] for it in q], ["RDR/ESP", "RDR/ESP", "DTM/ESP", "EDR/ESP"])

    def test_queue_is_deterministic(self):
        a = extras_pass.iter_queue(self._catalogue())
        b = extras_pass.iter_queue(self._catalogue())
        self.assertEqual([extras_pass.item_key(x) for x in a], [extras_pass.item_key(x) for x in b])

    def test_branch_filter(self):
        q = extras_pass.iter_queue(self._catalogue(), ["DTM/ESP"])
        self.assertEqual([it["name"] for it in q], ["ESP_011350_1560_ESP_011400_1560"])

    def test_is_done_reads_report_and_ignores_failures(self):
        with tempfile.TemporaryDirectory() as d:
            item = extras_pass.iter_queue(self._catalogue())[0]
            key = extras_pass.item_key(item)
            work = Path(d, *key.split("/"))
            self.assertFalse(extras_pass.is_done(item, d))
            work.mkdir(parents=True)
            (work / "report.json").write_text(json.dumps({"status": "partial"}), encoding="utf-8")
            self.assertFalse(extras_pass.is_done(item, d), "a partial run must be retried")
            (work / "report.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
            self.assertTrue(extras_pass.is_done(item, d))

    def test_propagate_geometry_fills_unlabelled_siblings(self):
        """Lighting geometry is copied across renderings; pixel scale is not."""
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["path", "name", "observation_id", "incidence_angle",
                      "solar_azimuth", "solar_elevation", "pixel_scale_m"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"path": "ESP_1_MIRB.browse.jpg", "name": "ESP_1_MIRB.browse.jpg",
                            "observation_id": "ESP_1", "incidence_angle": "57.5",
                            "solar_azimuth": "171.16", "solar_elevation": "32.49",
                            "pixel_scale_m": "0.5"})
                # the B&W RED reference ships no label of its own
                w.writerow({"path": "ESP_1_RED.browse.jpg", "name": "ESP_1_RED.browse.jpg",
                            "observation_id": "ESP_1", "incidence_angle": "",
                            "solar_azimuth": "", "solar_elevation": "",
                            "pixel_scale_m": ""})
            filled = extras_pass.propagate_geometry(csv_path, "ESP_1")
            self.assertEqual(filled, 3)  # incidence + azimuth + elevation
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            red = rows["ESP_1_RED.browse.jpg"]
            self.assertEqual(red["incidence_angle"], "57.5")
            self.assertEqual(red["solar_azimuth"], "171.16")
            self.assertEqual(red["solar_elevation"], "32.49")
            # a NOMAP product and a thumbnail have a different ground scale
            # from the map-projected browse, so scale must NOT be copied
            self.assertEqual(red["pixel_scale_m"], "")

    def test_pixel_scale_only_onto_an_identical_rendering_class(self):
        """Map scale belongs to the rendering, not the observation.

        The map-projected RED browse shares a grid with the labelled
        map-projected MIRB browse, so it inherits 0.5 m/px. A thumbnail and a
        detector-geometry (NOMAP) product do not, and copying the scale onto
        them would make the adjudicator turn a shadow into a height using the
        wrong metres-per-pixel.
        """
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "observation_id", "incidence_angle", "pixel_scale_m"]
            names = [
                "ESP_011261_1960_MIRB.browse.jpg",     # labelled source: map/browse
                "ESP_011261_1960_RED.browse.jpg",      # map/browse  -> inherits
                "ESP_011261_1960_RED.thumb.jpg",       # map/thumb   -> must NOT
                "ESP_011261_1960_RED.NOMAP.browse.jpg",  # nomap/browse -> must NOT
            ]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"name": names[0], "observation_id": "ESP_011261_1960",
                            "incidence_angle": "57.5", "pixel_scale_m": "0.5"})
                for n in names[1:]:
                    w.writerow({"name": n, "observation_id": "", "incidence_angle": "",
                                "pixel_scale_m": ""})
            products = [
                {"name": "ESP_011261_1960_MIRB.browse.jpg", "geometry": "map", "scale": "browse"},
                {"name": "ESP_011261_1960_RED.browse.jpg", "geometry": "map", "scale": "browse"},
                {"name": "ESP_011261_1960_RED.thumb.jpg", "geometry": "map", "scale": "thumb"},
                {"name": "ESP_011261_1960_RED.NOMAP.browse.jpg", "geometry": "nomap", "scale": "browse"},
            ]
            extras_pass.propagate_geometry(csv_path, "ESP_011261_1960", products)
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["ESP_011261_1960_RED.browse.jpg"]["pixel_scale_m"], "0.5")
            self.assertEqual(rows["ESP_011261_1960_RED.thumb.jpg"]["pixel_scale_m"], "")
            self.assertEqual(rows["ESP_011261_1960_RED.NOMAP.browse.jpg"]["pixel_scale_m"], "")

    def test_scale_is_not_propagated_without_a_rendering_profile(self):
        """With no classification available, refuse rather than guess."""
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "observation_id", "incidence_angle", "pixel_scale_m"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"name": "ESP_1_MIRB.browse.jpg", "observation_id": "ESP_1",
                            "incidence_angle": "50", "pixel_scale_m": "0.5"})
                w.writerow({"name": "ESP_1_RED.browse.jpg", "observation_id": "",
                            "incidence_angle": "", "pixel_scale_m": ""})
            extras_pass.propagate_geometry(csv_path, "ESP_1", products=None)
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["ESP_1_RED.browse.jpg"]["pixel_scale_m"], "")

    def test_downsampled_scale_is_corrected_from_pixel_width(self):
        """A thumbnail must not inherit the full-resolution label's scale.

        `_find_label` strips the scale token to find the sibling label, so a
        `.thumb.jpg` resolves to the map-projected label and reads 0.5 m/px
        verbatim. Reporting a thumbnail at full-browse resolution makes the
        adjudicator infer shadow heights 8x too small, so the scale is
        corrected from the actual pixel width instead of guessed from the name.
        """
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "observation_id", "incidence_angle", "pixel_scale_m", "width"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"name": "ESP_1_MIRB.browse.jpg", "observation_id": "ESP_1",
                            "incidence_angle": "50", "pixel_scale_m": "0.5", "width": "2048"})
                w.writerow({"name": "ESP_1_RED.browse.jpg", "observation_id": "",
                            "incidence_angle": "", "pixel_scale_m": "0.5", "width": "2048"})
                # a thumbnail of the same terrain: 1/8 the width
                w.writerow({"name": "ESP_1_MIRB.thumb.jpg", "observation_id": "",
                            "incidence_angle": "", "pixel_scale_m": "0.5", "width": "256"})
            products = [
                {"name": "ESP_1_MIRB.browse.jpg", "geometry": "map", "scale": "browse"},
                {"name": "ESP_1_RED.browse.jpg", "geometry": "map", "scale": "browse"},
                {"name": "ESP_1_MIRB.thumb.jpg", "geometry": "map", "scale": "thumb"},
            ]
            extras_pass.propagate_geometry(csv_path, "ESP_1", products)
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            self.assertEqual(float(rows["ESP_1_MIRB.browse.jpg"]["pixel_scale_m"]), 0.5)
            self.assertEqual(float(rows["ESP_1_RED.browse.jpg"]["pixel_scale_m"]), 0.5)
            # 2048/256 = 8x coarser
            self.assertAlmostEqual(float(rows["ESP_1_MIRB.thumb.jpg"]["pixel_scale_m"]), 4.0, places=3)

    def test_scale_correction_is_skipped_without_widths(self):
        rows = [{"name": "a", "pixel_scale_m": "0.5", "width": ""}]
        self.assertEqual(extras_pass.correct_downsampled_scale(rows, ["pixel_scale_m", "width"], {}), 0)

    def test_propagate_geometry_leaves_other_observations_alone(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "observation_id", "incidence_angle", "solar_azimuth"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerow({"name": "a", "observation_id": "ESP_1", "incidence_angle": "50", "solar_azimuth": "10"})
                w.writerow({"name": "b", "observation_id": "ESP_2", "incidence_angle": "", "solar_azimuth": ""})
            extras_pass.propagate_geometry(csv_path, "ESP_1")
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            self.assertEqual(rows["b"]["incidence_angle"], "")

    def test_propagate_geometry_matches_rows_that_lack_an_observation_id(self):
        """The RED reference ships no label, so it has no observation_id either.

        Matching only on `observation_id` silently skips exactly the rows the
        propagation exists to repair, leaving every candidate found on the
        reference without a solar incidence angle.
        """
        with tempfile.TemporaryDirectory() as d:
            csv_path = os.path.join(d, "catalog.csv")
            fields = ["name", "path", "observation_id", "incidence_angle", "solar_azimuth"]
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                # the only labelled product
                w.writerow({"name": "ESP_011261_1960_MIRB.browse.jpg", "path": "x/ESP_011261_1960_MIRB.browse.jpg",
                            "observation_id": "ESP_011261_1960", "incidence_angle": "57.508291",
                            "solar_azimuth": "171.160759"})
                # the B&W RED reference: no label, hence a blank observation_id
                w.writerow({"name": "ESP_011261_1960_RED.browse.jpg", "path": "x/ESP_011261_1960_RED.browse.jpg",
                            "observation_id": "", "incidence_angle": "", "solar_azimuth": ""})
            filled = extras_pass.propagate_geometry(csv_path, "ESP_011261_1960")
            self.assertGreaterEqual(filled, 2)
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = {r["name"]: r for r in csv.DictReader(f)}
            red = rows["ESP_011261_1960_RED.browse.jpg"]
            self.assertEqual(red["incidence_angle"], "57.508291")
            self.assertEqual(red["solar_azimuth"], "171.160759")
            self.assertEqual(red["observation_id"], "ESP_011261_1960")


if __name__ == "__main__":
    unittest.main()
