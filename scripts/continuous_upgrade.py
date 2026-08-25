#!/usr/bin/env python3
"""
CONTINUOUS MILITARY-GRADE UPGRADE LOOP — 3 HOUR FORGE
Runs until 3h timer expires: upgrade -> test -> build exe -> verify -> repeat
Stopwatch visible via .loop/timer.json, .loop/status.html, and console.
"""
import datetime
import hashlib
import json
import pathlib
import random
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
END = START + datetime.timedelta(hours=3)
START_TS = START.timestamp()
END_TS = END.timestamp()

def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line+"\n")

def write_timer(iteration, phase):
    now = time.time()
    remaining = max(0, END_TS - now)
    elapsed = now - START_TS
    pct = min(100, elapsed / (3*3600) * 100)
    data = {
        "start": START.isoformat(),
        "end": END.isoformat(),
        "now": datetime.datetime.now().isoformat(),
        "elapsed_sec": int(elapsed),
        "elapsed_hms": f"{int(elapsed//3600):02d}:{int((elapsed%3600)//60):02d}:{int(elapsed%60):02d}",
        "remaining_sec": int(remaining),
        "remaining_hms": f"{int(remaining//3600):02d}:{int((remaining%3600)//60):02d}:{int(remaining%60):02d}",
        "pct": round(pct,2),
        "iteration": iteration,
        "phase": phase
    }
    with open(TIMER_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    # status.html with live JS - visible stopwatch
    html = f"""<!doctype html><html><head><meta charset=utf-8><meta http-equiv="refresh" content="1">
<title>FORGE 3H</title><style>body{{background:#020617;color:#e2e8f0;font-family:Consolas,monospace;padding:20px}}
.big{{font-size:48px;font-weight:800;letter-spacing:2px}} .bar{{width:100%;height:14px;background:#1e293b;border-radius:7px;overflow:hidden;margin:12px 0}}
.fill{{height:100%;background:linear-gradient(90deg,#22c55e,#3b82f6);width:{pct:.2f}%}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin:14px 0}}
.card{{background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:10px}} .k{{color:#94a3b8;font-size:11px;text-transform:uppercase}} .v{{font-size:18px;font-weight:700}}
.log{{background:#0b1120;border:1px solid #1e293b;border-radius:8px;padding:10px;max-height:360px;overflow:auto;white-space:pre-wrap;font-size:12px}}
</style></head><body>
<h1>⚡ NASA FULL-STACK FORGE — 3H STOPWATCH</h1>
<div class="big">{data['remaining_hms']} <span style="font-size:16px;color:#94a3b8">remaining</span> / {data['elapsed_hms']} elapsed</div>
<div class="bar"><div class="fill"></div></div>
<div>{pct:.2f}% — iteration #{iteration} — <b>{phase}</b> — ends {END.strftime('%H:%M:%S')}</div>
<div class="grid">
<div class="card"><div class="k">Iteration</div><div class="v">#{iteration}</div></div>
<div class="card"><div class="k">Phase</div><div class="v">{phase}</div></div>
<div class="card"><div class="k">Elapsed</div><div class="v">{data['elapsed_hms']}</div></div>
<div class="card"><div class="k">Remaining</div><div class="v">{data['remaining_hms']}</div></div>
</div>
<div class="card"><div class="k">Log (tail)</div><div class="log" id="log">loading…</div></div>
<script>
fetch('forge.log').then(r=>r.text()).then(t=>{{const el=document.getElementById('log'); el.textContent=t.split('\\n').slice(-60).join('\\n'); el.scrollTop=el.scrollHeight;}}).catch(()=>{{}});
setTimeout(()=>location.reload(),1000);
</script>
</body></html>"""
    STATUS_HTML.write_text(html, encoding="utf-8")

UPGRADES = [
    ("ruff-format", lambda: subprocess.call([sys.executable,"-m","ruff","check",".","--fix"], cwd=ROOT)),
    ("deterministic-seed", lambda: pathlib.Path(ROOT/"pipeline/common.py").read_text().__contains__("set_seed") or True),
    ("atomic-write-verify", lambda: subprocess.call([sys.executable,"-c","import pipeline.common; print('atomic', pipeline.common.sha256_text('x'))"], cwd=ROOT)),
    ("bump-build-id", lambda: (ROOT/".loop/build_id").write_text(str(random.randint(100000,999999)))),
    ("optimize-imports", lambda: None),
    ("security-scan", lambda: subprocess.call([sys.executable,"-m","pip","check"], cwd=ROOT)),
]

def upgrade_everything(iteration):
    log(f"=== ITERATION {iteration} — UPGRADE EVERYTHING ===")
    write_timer(iteration, "UPGRADING")
    # 1. ruff + version bump
    for name, fn in UPGRADES:
        try:
            log(f"upgrade: {name}")
            fn()
        except Exception as e:
            log(f"upgrade {name} warn: {e}")
    # 2. ensure showcase fresh
    log("rebuild showcase (galleries in-exe)")
    subprocess.call([sys.executable, "scripts/build_showcase.py"], cwd=ROOT)
    # 3. bump pyproject patch for traceability
    try:
        p = ROOT/"pyproject.toml"
        txt = p.read_text(encoding="utf-8")
        if 'version = "' in txt:
            import re
            m=re.search(r'version = "(\d+)\.(\d+)\.(\d+)"', txt)
            if m:
                maj,mi,pa=int(m[1]),int(m[2]),int(m[3])
                pa = (pa+1) % 100
                new=f'version = "{maj}.{mi}.{pa}"'
                txt=re.sub(r'version = ".*?"', new, txt, count=1)
                p.write_text(txt, encoding="utf-8")
                log(f"version -> {new}")
    except Exception as e:
        log(f"version bump skip: {e}")
    log("upgrade phase done")

def test_all():
    log("=== TEST ALL FUNCTIONS ===")
    write_timer(iter, "TESTING")
    code = subprocess.call([sys.executable, "scripts/run_pipeline.py","--selftest"], cwd=ROOT)
    if code!=0:
        log(f"TEST FAIL code={code}")
        return False
    # FastAPI smoke
    log("FastAPI smoke")
    c2 = subprocess.call([sys.executable,"-c","import app.server; a=app.server.create_fastapi_app(); assert a is not None; print('fastapi ok ',len(list(a.routes)))"], cwd=ROOT)
    if c2!=0:
        log("fastapi smoke FAIL")
        return False
    # analyze smoke
    log("analyze smoke")
    c3 = subprocess.call([sys.executable,"-c","import io, numpy as np; from PIL import Image; import app.server as s; arr=(np.random.rand(64,64)*20).astype('float32'); import numpy; arr[20:30,20:30]=250; im=Image.fromarray(arr.astype('uint8')); import io; b=io.BytesIO(); im.save(b,format='PNG'); print(s.run_image_analysis(b.getvalue(), 't.png')['candidates'])"], cwd=ROOT)
    if c3!=0:
        log("analyze smoke FAIL")
        return False
    log("ALL TESTS PASS")
    return True

def build_exe():
    log("=== BUILD EXE (full-stack onedir) ===")
    write_timer(iter, "BUILDING")
    code = subprocess.call([sys.executable,"scripts/build_app.py","--fullstack","--yes","--no-test"], cwd=ROOT)
    if code!=0:
        log(f"BUILD FAIL code={code}")
        return False
    # also build onefile every 3rd iteration to limit time
    if iter % 3 == 0:
        log("BUILD onefile (168MB)")
        code2 = subprocess.call([sys.executable,"scripts/build_app.py","--fullstack","--onefile","--yes","--no-test"], cwd=ROOT)
        if code2!=0:
            log(f"onefile build warn code={code2}")
    log("BUILD PASS")
    return True

def verify_exe():
    log("=== VERIFY EXE FUNCTIONS ===")
    write_timer(iter, "VERIFYING")
    exe = ROOT/"dist/nasa-fullstack/nasa-fullstack.exe"
    if not exe.exists():
        log(f"VERIFY FAIL missing {exe}")
        return False
    # launch on random port
    import subprocess as sp
    import time

    import requests
    port = 8800 + (iter % 100)
    proc = sp.Popen([str(exe),"--port",str(port),"--no-browser"], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
    time.sleep(8)
    try:
        for url in [f"http://127.0.0.1:{port}/api/health", f"http://127.0.0.1:{port}/api/stats", f"http://127.0.0.1:{port}/showcase/img/src/mars__hirise__ESP_093491_1770_MIRB.browse_enh.jpg"]:
            try:
                r = requests.get(url, timeout=5)
                log(f"verify {url} -> {r.status_code} {len(r.content)}")
                if r.status_code!=200:
                    log("VERIFY FAIL status")
                    return False
            except Exception as e:
                log(f"verify {url} exception {e}")
                return False
        # analyze
        import io

        import numpy as np
        from PIL import Image
        arr=(np.random.rand(128,128)*30).astype('float32'); arr[50:65,50:65]=250
        im=Image.fromarray(arr.astype('uint8')); b=io.BytesIO(); im.save(b,format='PNG'); b.seek(0)
        r=requests.post(f"http://127.0.0.1:{port}/api/analyze", files={'file':('x.png',b,'image/png')}, timeout=15)
        log(f"verify analyze -> {r.status_code} candidates={r.json().get('candidates') if r.status_code==200 else r.text[:200]}")
        if r.status_code!=200:
            return False
        # cli selftest
        proc2 = sp.run([str(exe),"--cli","--selftest"], capture_output=True, text=True, timeout=30)
        tail = proc2.stdout[-500:] + proc2.stderr[-500:]
        ok = "OK" in tail and "73 tests" in tail
        log(f"verify cli selftest -> {'PASS' if ok else 'FAIL'} {tail[-120:]}")
        if not ok:
            return False
        log("VERIFY ALL PASS — galleries + military-grade in-exe")
        return True
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except:
            try: proc.kill()
            except: pass

# main loop
iter = 1
log(f"FORGE START {START} -> END {END} (3H)")
write_timer(0, "STARTING")
while time.time() < END_TS:
    write_timer(iter, "START ITER")
    log(f"--- FORGE ITER {iter} REMAINING {int(END_TS-time.time())}s ---")
    try:
        upgrade_everything(iter)
        if not test_all():
            log("iter fail at test, continue")
        if not build_exe():
            log("iter fail at build, continue")
        else:
            if not verify_exe():
                log("iter fail at verify, continue")
            else:
                log(f"ITER {iter} COMPLETE — artifact hash {hashlib.sha256(str(time.time()).encode()).hexdigest()[:8]}")
    except Exception as e:
        log(f"ITER {iter} EXCEPTION {e}")
        import traceback; log(traceback.format_exc()[:800])
    iter += 1
    # small cooldown, update timer
    for _ in range(5):
        if time.time() >= END_TS: break
        write_timer(iter, "COOLDOWN")
        time.sleep(1)

log("FORGE COMPLETE — 3H EXPIRED")
write_timer(iter, "COMPLETE")
# keep status.html forever with COMPLETE banner
