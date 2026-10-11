#!/usr/bin/env python3
"""
Supervisor for the long-running EXTRAS jobs
===========================================
The HiRISE PDS archive serves roughly one index request per 10 s and refuses
(HTTP 503) beyond ~8 concurrent connections, so indexing the whole EXTRAS
tree takes many hours. Anything that kills the process — a server restart, a
terminal close, an idle OOM kill — loses nothing, because the listing cache
and the per-image ``report.json`` files make both jobs resumable. What it does
lose is the *supervision*: the job has to be restarted by hand, and it has been
killed four times in this project already.

This script runs the two long jobs and restarts them on unexpected exit::

    catalogue   scripts/catalog_extras_site.py   index the whole EXTRAS tree
    pass        scripts/extras_pass.py            one image at a time, full pipeline

Both are safe to relaunch at any moment. The supervisor adds:

  * **restart on exit** with capped exponential backoff, up to ``--max-restarts``;
  * **stall detection** — if a job makes no progress for ``--stall-seconds`` it
    is killed and relaunched, so a job wedged on a dead socket does not sit
    there forever;
  * **bounded concurrency against the archive** — the two jobs run together but
    the pass is throttled to ``--pass-file-workers`` so total in-flight
    requests stay near the host's 503 threshold;
  * **honest logging** — a single supervisor log with timestamps, plus the
    child's own output streamed through.

Usage
-----
::

    # both, in the background, restarting as needed
    python scripts/run_extras_pipeline.py --both

    # just the catalogue, for at most 12 hours
    python scripts/run_extras_pipeline.py --catalogue --max-hours 12

    # the pass alone, throttled to 2 concurrent downloads
    python scripts/run_extras_pipeline.py --pass --pass-file-workers 2

    # is it healthy?
    python scripts/run_extras_pipeline.py --status
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_ROOT, os.path.join(_ROOT, "pipeline"), os.path.join(_ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import common  # noqa: E402

SUPERVISOR_SCHEMA = "extras-supervisor/1"


# ---------------------------------------------------------------------------
# Progress probes — how the supervisor tells "working" from "wedged"
# ---------------------------------------------------------------------------


def catalogue_progress(catalogue_path: str) -> tuple[int, int, float]:
    """(shards seen, footprints seen, mtime age of the catalogue)."""
    if not os.path.exists(catalogue_path):
        return 0, 0, 1e9
    try:
        age = time.time() - os.path.getmtime(catalogue_path)
    except OSError:
        return 0, 0, 1e9
    shards = footprints = 0
    try:
        with open(catalogue_path, encoding="utf-8") as f:
            cat = json.load(f)
        for br in cat.get("branches", []):
            shards += len(br.get("shards", []))
            footprints += br.get("footprint_count", 0)
    except Exception:  # noqa: BLE001
        return 0, 0, age
    return shards, footprints, age


def catalogue_probe(path: str) -> tuple[int, float]:
    """Job-probe view of the catalogue: (footprints, seconds since last write).

    ``catalogue_progress`` also reports the shard count for ``--status``; the
    supervisor's stall check only needs a single monotonic value plus the
    file's age, so the probe contract stays two-tuple for every job.
    """
    _shards, footprints, age = catalogue_progress(path)
    return footprints, age


def pass_progress(out_root: str) -> tuple[int, float]:
    """(images processed, mtime age of state.json)."""
    state = os.path.join(out_root, "state.json")
    if not os.path.exists(state):
        return 0, 1e9
    try:
        age = time.time() - os.path.getmtime(state)
    except OSError:
        return 0, 1e9
    try:
        with open(state, encoding="utf-8") as f:
            return int(json.load(f).get("processed") or 0), age
    except Exception:  # noqa: BLE001
        return 0, age


def ago(seconds: float) -> str:
    if seconds > 1e8:
        return "never"
    if seconds < 90:
        return f"{seconds:.0f}s ago"
    if seconds < 5400:
        return f"{seconds/60:.0f}m ago"
    return f"{seconds/3600:.1f}h ago"


#: Serialises writes to the shared supervisor log and the console.
LOG_LOCK = threading.Lock()


class Job:
    """One supervised child process.

    Lifecycle: started once, then relaunched on a non-zero exit or a stall, up
    to ``max_restarts``. A clean exit (0) is final — both jobs exit 0 when they
    genuinely have nothing left to do, or when a budget such as
    ``--disk-floor-gb`` stops them, and relaunching in either case would just
    spin.
    """

    def __init__(self, name: str, argv: list[str], probe, stall_seconds: float,
                 log_path: str, wake=None, wake_cooldown: float = 120.0):
        self.name = name
        self.argv = argv
        self.probe = probe
        self.stall_seconds = stall_seconds
        self.log_path = log_path
        #: Optional predicate: "restart me if this becomes true". Used for the
        #: pass, which legitimately exhausts its queue while the catalogue is
        #: still growing and would otherwise never pick up the new images.
        self.wake = wake
        self.wake_cooldown = wake_cooldown
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.finished = False
        self._wake_seen = None
        self._wake_at = 0.0
        self._reader: threading.Thread | None = None

    def start(self) -> None:
        self._emit(f"--- starting (restart #{self.restarts})")
        self.proc = subprocess.Popen(
            self.argv, cwd=_ROOT, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1,
            encoding="utf-8", errors="replace",
        )
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        """Stream the child's output into the shared log, line by line."""
        if not self.proc or not self.proc.stdout:
            return
        for line in self.proc.stdout:
            self._emit(line.rstrip("\n"))

    def _emit(self, msg: str) -> None:
        """Write one line to the log file and, best effort, the console.

        The console write is guarded on purpose: a supervisor exists to keep
        the children alive, and it must not take itself down because stdout
        was closed underneath it (a closed pipe, a detached terminal, a
        redirect that ended). The log file is the durable record; the console
        is a convenience.
        """
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {self.name}: {msg}"
        with LOG_LOCK:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                # console is gone; the file write above already succeeded
                pass

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def progress(self):
        return self.probe()

    def stop(self, sig=signal.SIGTERM) -> None:
        if self.alive():
            try:
                self.proc.terminate()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            try:
                self.proc.wait(timeout=30)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()  # type: ignore[union-attr]
                except Exception:  # noqa: BLE001
                    pass
        self._emit("stopped")

    def wait(self, timeout: float | None = None) -> int:
        if not self.proc:
            return 0
        try:
            return self.proc.wait(timeout=timeout)
        except Exception:  # noqa: BLE001
            return -1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_jobs(args) -> list[Job]:
    jobs: list[Job] = []
    if args.catalogue:
        cat_argv = [
            sys.executable, os.path.join("scripts", "catalog_extras_site.py"),
            "--workers", str(args.crawl_workers),
            "--scales", args.scales, "--geometries", args.geometries,
            "--checkpoint-seconds", str(args.checkpoint_seconds),
            # Merge into the existing catalogue. Without this a relaunch
            # discards the previous run's branch records, so a supervisor that
            # restarts often would keep resetting the catalogue's progress.
            "--append",
        ]
        if args.branches:
            cat_argv += ["--branches", args.branches]
        jobs.append(Job(
            "catalogue", cat_argv,
            probe=lambda: catalogue_probe(args.catalogue_path),
            stall_seconds=args.catalogue_stall, log_path=args.log,
        ))
    if args.pass_ or args.both:
        pass_argv = [
            sys.executable, os.path.join("scripts", "extras_pass.py"),
            "--out", args.out, "--file-workers", str(args.pass_file_workers),
            "--disk-floor-gb", str(args.disk_floor_gb),
        ]
        if args.branches:
            pass_argv += ["--branches", args.branches]
        if args.limit:
            pass_argv += ["--limit", str(args.limit)]

        def _catalogue_grew() -> bool:
            """Has the catalogue gained images since the pass last drained?

            The pass reads whatever the catalogue contains at start-up and
            exits when that queue is exhausted, which happens long before the
            crawl finishes. Without this the supervisor would treat the first
            drain as the end of the run and no further image would ever be
            picked up.
            """
            now_value, _age = catalogue_probe(args.catalogue_path)
            seen = next((j for j in jobs if j.name == "pass"), None)
            if seen is None or seen._wake_seen is None:
                return False
            return now_value > seen._wake_seen

        jobs.append(Job(
            "pass", pass_argv,
            probe=lambda: pass_progress(args.out),
            stall_seconds=args.pass_stall, log_path=args.log,
            wake=_catalogue_grew, wake_cooldown=args.wake_cooldown,
        ))
    return jobs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Supervise the long-running EXTRAS catalogue and pass jobs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--catalogue", action="store_true", help="run the site catalogue crawler")
    p.add_argument("--pass", dest="pass_", action="store_true", help="run the systematic image pass")
    p.add_argument("--both", action="store_true", help="run both (default)")
    p.add_argument("--status", action="store_true", help="report on the jobs and exit")
    p.add_argument("--catalogue-path", default="data/catalog/extras_site.json")
    p.add_argument("--out", default="data/processed/extras_pass", help="pass output root")
    p.add_argument("--log", default="data/catalog/extras_supervisor.log")
    p.add_argument("--branches", default="", help="branch filter passed to both jobs")
    p.add_argument("--scales", default="core", choices=("thumb", "browse", "core", "full"))
    p.add_argument("--geometries", default="map", choices=("map", "all"))
    p.add_argument("--limit", type=int, default=0, help="pass --limit (per relaunch)")
    p.add_argument("--crawl-workers", type=int, default=6,
                   help="catalogue index concurrency; the host 503s above ~8 in total")
    p.add_argument("--pass-file-workers", type=int, default=2,
                   help="concurrent downloads inside the pass; keep the combined total near 8")
    p.add_argument("--disk-floor-gb", type=float, default=100.0)
    p.add_argument("--checkpoint-seconds", type=float, default=240.0)
    p.add_argument("--catalogue-stall", type=float, default=3600.0,
                   help="restart the crawler if its catalogue goes unwritten this long")
    p.add_argument("--pass-stall", type=float, default=1800.0,
                   help="restart the pass if state.json goes unwritten this long")
    p.add_argument("--max-restarts", type=int, default=50)
    p.add_argument("--wake-cooldown", type=float, default=180.0,
                   help="seconds to wait before re-checking whether the catalogue grew")
    p.add_argument("--max-hours", type=float, default=0.0, help="supervisor wall-clock cap (0 = no cap)")
    args = p.parse_args(argv)

    if not (args.catalogue or args.pass_ or args.both or args.status):
        args.both = True
    if args.both:
        args.catalogue = True
        args.pass_ = True

    if args.status:
        cs, cf, cage = catalogue_progress(args.catalogue_path)
        pi, piage = pass_progress(args.out)
        common.log("info", f"catalogue: {cf:,} footprints in {cs:,} shards, "
                           f"last written {ago(cage)}")
        common.log("info", f"pass: {pi:,} images, last written {ago(piage)}")
        if os.path.exists(args.log):
            common.log("info", f"supervisor log: {args.log} "
                               f"({os.path.getsize(args.log)/1024:.0f} KB)")
        return 0

    os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
    jobs = build_jobs(args)
    if not jobs:
        common.log("error", "nothing selected")
        return 2

    with LOG_LOCK:
        with open(args.log, "a", encoding="utf-8") as f:
            f.write(f"\n=== session {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"jobs={[j.name for j in jobs]} ===\n")
        try:
            print(f"=== EXTRAS supervisor starting {len(jobs)} job(s) ===", flush=True)
        except (OSError, ValueError):
            pass

    def _console(msg: str) -> None:
        """Supervisor notice, safe against a closed or vanished stdout.

        ``common.log`` prints unguarded, which is right for the pipeline but
        wrong here: this process is a long-lived supervisor whose only job is
        to keep the children alive, and a console that has gone away (a closed
        pipe, a detached terminal) must not be able to end it.
        """
        with LOG_LOCK:
            try:
                with open(args.log, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] [supervisor] {msg}\n")
            except OSError:
                pass
            try:
                print(f"[supervisor] {msg}", flush=True)
            except (OSError, ValueError):
                pass

    def _on_signal(signum, _frame):
        _console(f"signal {signum}: stopping children")
        for j in jobs:
            j.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    t0 = time.time()
    last_seen = {j.name: (None, time.time()) for j in jobs}
    backoff = 5.0

    def _banner(job: Job, msg: str) -> None:
        """Supervisor-level event, written to the log even with no console."""
        with LOG_LOCK:
            line = f"=== {job.name} {msg} ==="
            try:
                with open(args.log, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
            except OSError:
                pass
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass

    def supervise(job: Job) -> None:
        """One supervision tick for a job: start, restart, stall-kill, or leave it.

        Declares ``backoff`` nonlocal: it reads and advances the shared
        restart delay, and a plain assignment here would shadow the enclosing
        one and make the read an UnboundLocalError.
        """
        nonlocal backoff
        # A finished job can still be woken: the pass drains its queue whenever
        # the catalogue it reads has been fully ingested, and the catalogue
        # keeps growing for hours afterwards.
        if job.finished:
            if job.wake is None or time.time() - job._wake_at < job.wake_cooldown:
                return
            if job.wake():
                job._wake_at = time.time()
                job.finished = False
                job.restarts += 1
                if job.restarts <= args.max_restarts:
                    _banner(job, "catalogue grew; picking up the new images")
                    job.start()
            return
        if job.proc is None:
            job.start()
            return

        if job.alive():
            value, _age = job.progress()
            prev, prev_t = last_seen[job.name]
            if prev is None or value != prev:
                last_seen[job.name] = (value, time.time())
            elif time.time() - prev_t > job.stall_seconds:
                _banner(job, f"no progress for {job.stall_seconds:.0f}s; restarting")
                job.stop()
                job.restarts += 1
                last_seen[job.name] = (value, time.time())
                if job.restarts <= args.max_restarts:
                    job.start()
                else:
                    job.finished = True
            return

        # not alive: the child exited
        rc = job.proc.returncode
        if rc == 0:
            job.finished = True
            job._wake_at = time.time()
            job._wake_seen = job.progress()[0] if job.wake is not None else None
            job._emit("exited cleanly; done" + (" (will re-check for new work)" if job.wake else ""))
            return
        if job.restarts >= args.max_restarts:
            job.finished = True
            job._emit(f"exited {rc}; giving up after {args.max_restarts} restarts")
            return
        _banner(job, f"exited {rc}; restarting in {backoff:.0f}s")
        time.sleep(backoff)
        backoff = min(backoff * 1.5, 300.0)
        job.restarts += 1
        job.start()

    def _check_budget(jobs: list[Job]) -> int | None:
        """Return an exit code when the supervisor should stop, else None."""
        if args.max_hours and (time.time() - t0) / 3600.0 >= args.max_hours:
            _console(f"--max-hours {args.max_hours} reached; stopping children")
            for j in jobs:
                j.stop()
            return 0
        if jobs and all(j.finished for j in jobs):
            failed = [j for j in jobs if j.proc and j.proc.returncode not in (0, None)]
            _console("all jobs finished"
                     + (f" (gave up: {[j.name for j in failed]})" if failed else ""))
            return 1 if failed else 0
        return None

    while True:
        for j in jobs:
            # A supervision bug must never be fatal. This process exists purely
            # to keep the children alive; if the loop itself raises, log it and
            # try again next tick rather than leaving both jobs unsupervised.
            # A real one of these cost a run: a plain assignment to the
            # enclosing `backoff` shadowed it, raised UnboundLocalError, and
            # took the supervisor down with it.
            try:
                supervise(j)
            except Exception as e:  # noqa: BLE001
                _console(f"supervise({j.name}) raised {type(e).__name__}: {e} "
                         f"-- continuing, children left running")
        try:
            code = _check_budget(jobs)
        except Exception as e:  # noqa: BLE001
            _console(f"budget check raised {type(e).__name__}: {e}")
            code = None
        if code is not None:
            return code
        time.sleep(5)


if __name__ == "__main__":
    raise SystemExit(main())
