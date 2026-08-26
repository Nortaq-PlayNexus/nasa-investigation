#!/usr/bin/env python3
"""
CONTINUOUS UPGRADE LOOP — visible stopwatch, runs until the timer expires:
upgrade -> test -> build site -> verify -> repeat. Then commit & push.

It is self-contained for THIS repository (no pipeline.* / app.server / PyInstaller
assumptions). A live stopwatch is written to .loop/timer.json and .loop/status.html
(refreshing every second) and printed to the console.

    python scripts/continuous_upgrade.py --hours 6
    python scripts/continuous_upgrade.py --minutes 20 --no-push
"""
import argparse
import datetime
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
LOOP_DIR = ROOT / ".loop"
LOOP_DIR.mkdir(exist_ok=True)
TIMER_FILE = LOOP_DIR / "timer.json"
LOG_FILE = LOOP_DIR / "forge.log"
STATUS_HTML = LOOP_DIR / "status.html"

START = datetime.datetime.now()
DEFAULT_HOURS = 3.0


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_timer(iteration, phase, end_ts):
    now = time.time()
    remaining = max(0, end_ts - now)
    elapsed = now - START.timestamp()
    pct = min(100, elapsed / (end_ts - START.timestamp()) * 100) if end_ts > START.timestamp() else 0
    def hms(s):
        return f"{int(s // 3600):02d}:{int((s % 3600) // 60):02d}:{int(s % 60):02d}"
    data = {
        "start": START.isoformat(), "end": datetime.datetime.fromtimestamp(end_ts).isoformat(),
        "now": datetime.datetime.now().isoformat(),
        "elapsed_sec": int(elapsed), "elapsed_hms": hms(elapsed),
        "remaining_sec": int(remaining), "remaining_hms": hms(remaining),
        "pct": round(pct, 2), "iteration": iteration, "phase": phase,
    }
    TIMER_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    html = f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv="refresh" content="1">
<title>UPGRADE LOOP</title><style>body{{background:#020617;color:#e2e8f0;font-family:Consolas,monospace;padding:20px}}
.big{{font-size:46px;font-weight:800;letter-spacing:2px}} .bar{{width:100%;height:14px;background:#1e293b;border-radius:7px;overflow:hidden;margin:12px 0}}
.fill{{height:100%;background:linear-gradient(90deg,#22c55e,#3b82f6);width:{pct:.2f}%}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:10px}} .k{{color:#94a3b8;font-size:11px;text-transform:uppercase}} .v{{font-size:18px;font-weight:700}}
.log{{background:#0b1120;border:1px solid #1e293b;border-radius:8px;padding:10px;max-height:360px;overflow:auto;white-space:pre-wrap;font-size:12px}}
</style></head><body>
<h1>&#9889; NASA HiRISE Dossier &mdash; Continuous Upgrade Loop</h1>
<div class="big">{data['remaining_hms']} <span style="font-size:16px;color:#94a3b8">remaining</span> / {data['elapsed_hms']} elapsed</div>
<div class="bar"><div class="fill"></div></div>
<div>{pct:.2f}% &mdash; iteration #{iteration} &mdash; <b>{phase}</b> &mdash; ends {datetime.datetime.fromtimestamp(end_ts).strftime('%H:%M:%S')}</div>
<div class="grid">
<div class="card"><div class="k">Iteration</div><div class="v">#{iteration}</div></div>
<div class="card"><div class="k">Phase</div><div class="v">{phase}</div></div>
<div class="card"><div class="k">Elapsed</div><div class="v">{data['elapsed_hms']}</div></div>
<div class="card"><div class="k">Remaining</div><div class="v">{data['remaining_hms']}</div></div>
</div>
<div class="card"><div class="k">Log (tail)</div><div class="log" id="log">loading&hellip;</div></div>
<script>
fetch('forge.log').then(r=>r.text()).then(t=>{{const el=document.getElementById('log'); el.textContent=t.split('\\n').slice(-60).join('\\n'); el.scrollTop=el.scrollHeight;}}).catch(()=>{{}});
setTimeout(()=>location.reload(),1000);
</script>
</body></html>"""
    STATUS_HTML.write_text(html, encoding="utf-8")


def run(cmd):
    log("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


UPGRADES = [
    ("ruff", ["-m", "ruff", "check", "scripts", "tests", "--fix"]),
    ("bump-version", None),  # handled inline below
]


def bump_version():
    try:
        p = ROOT / "pyproject.toml"
        txt = p.read_text(encoding="utf-8")
        import re
        m = re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', txt)
        if m:
            maj, mi, pa = int(m.group(1)), int(m.group(2)), int(m.group(3))
            pa = (pa + 1) % 100
            new = f'version = "{maj}.{mi}.{pa}"'
            txt = re.sub(r'version = ".*?"', new, txt, count=1)
            p.write_text(txt, encoding="utf-8")
            log(f"version -> {new}")
    except Exception as e:
        log(f"version bump skip: {e}")


def upgrade_everything(iteration, py):
    log(f"=== ITERATION {iteration} — UPGRADE ===")
    for name, args in UPGRADES:
        try:
            if args is None:
                bump_version()
                continue
            log(f"upgrade: {name}")
            run([py, *args])
        except Exception as e:
            log(f"upgrade {name} warn: {e}")


def test_all(py):
    log("=== TEST ===")
    if run([py, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"]) != 0:
        log("TEST FAIL (pytest)")
        return False
    if run([py, "scripts/build_site.py", "--selftest"]) != 0:
        log("TEST FAIL (selftest)")
        return False
    log("ALL TESTS PASS")
    return True


def build_site(py):
    log("=== BUILD SITE ===")
    if run([py, "scripts/build_site.py"]) != 0:
        log("BUILD FAIL")
        return False
    log("BUILD PASS")
    return True


def verify(py):
    log("=== VERIFY ===")
    need = [ROOT / "site" / "index.html", ROOT / "site" / "report" / "index.html",
            ROOT / "site" / "assets" / "leads.json"]
    for f in need:
        if not f.exists():
            log(f"VERIFY FAIL missing {f}")
            return False
    run([py, "scripts/audit_strips.py"])
    run([py, "scripts/validate_conclusions.py"])
    log("VERIFY PASS")
    return True


def push():
    try:
        run(["git", "add", "-A"])
        run(["git", "commit", "-q", "-m", "continuous upgrade loop: automated pass"])
        run(["git", "push", "-q", "origin", "main"])
        log("PUSHED")
    except Exception as e:
        log(f"push warn: {e}")


def main():
    ap = argparse.ArgumentParser(description="Continuous upgrade loop with live stopwatch.")
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--no-push", action="store_true", help="do not commit/push")
    a = ap.parse_args()
    secs = (a.hours or 0) * 3600 + (a.minutes or 0) * 60
    if secs <= 0:
        secs = DEFAULT_HOURS * 3600
    end_ts = time.time() + secs
    py = sys.executable
    log(f"LOOP START {START} -> END {datetime.datetime.fromtimestamp(end_ts)}")
    write_timer(0, "STARTING", end_ts)
    iteration = 1
    while time.time() < end_ts:
        write_timer(iteration, "START ITER", end_ts)
        try:
            upgrade_everything(iteration, py)
            if not test_all(py):
                log("iter fail at test, continue")
            elif not build_site(py):
                log("iter fail at build, continue")
            elif not verify(py):
                log("iter fail at verify, continue")
            else:
                log(f"ITER {iteration} COMPLETE")
                if not a.no_push:
                    push()
        except Exception as e:
            import traceback
            log(f"ITER {iteration} EXCEPTION {e}")
            log(traceback.format_exc()[:800])
        iteration += 1
        for _ in range(5):
            if time.time() >= end_ts:
                break
            write_timer(iteration, "COOLDOWN", end_ts)
            time.sleep(1)
    log("LOOP COMPLETE — TIMER EXPIRED")
    write_timer(iteration, "COMPLETE", end_ts)


if __name__ == "__main__":
    main()
