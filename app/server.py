"""Full-stack HTTP API + static server for NASA Investigation.

Serves:
 - Frontend at /  (app/static/index.html) and /showcase (showcase/index.html)
 - REST API at /api/*  (health, stats, features, analyze, pipeline)
 - Static data mounts at /data/* and /showcase/img/*

Designed to run both as:
   python app/server.py
   python -m app.server
   nasa-fullstack.exe  (PyInstaller frozen, sys._MEIPASS)

No external deps required for fallback; prefers FastAPI+uvicorn when available,
otherwise falls back to stdlib http.server for single-file EXE portability.
"""

import base64
import csv
import io
import json
import sys
import threading
import time
import traceback
import urllib.parse
from pathlib import Path

# ---------------------------------------------------------------------------
# Project root resolution (dev vs PyInstaller frozen)
# ---------------------------------------------------------------------------

def get_project_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller bundle: data is extracted to _MEIPASS, but writable data
        # stays next to the exe. Prefer exe-dir for data/config.
        exe_dir = Path(sys.executable).resolve().parent
        # If exe_dir contains data/, use it; otherwise use _MEIPASS for bundled template
        if (exe_dir / "config" / "pipeline.json").exists() or (exe_dir / "data").exists():
            return exe_dir
        return Path(sys._MEIPASS)  # type: ignore
    # dev: app/server.py -> project root is parent of app/
    return Path(__file__).resolve().parents[1]


ROOT = get_project_root()
PIPELINE_DIR = ROOT / "pipeline"
SCRIPTS_DIR = ROOT / "scripts"

# Make pipeline imports work regardless of frozen/dev
for p in (str(ROOT), str(PIPELINE_DIR), str(SCRIPTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# ---------------------------------------------------------------------------
# Helpers: safe reads with graceful empty fallbacks
# ---------------------------------------------------------------------------

def _safe_read_jsonl(path: Path, limit: int = 500) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
            if len(out) >= limit:
                break
    except Exception:
        pass
    return out


def _safe_read_csv(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            r = csv.DictReader(f)
            rows = list(r)
            if limit:
                return rows[:limit]
            return rows
    except Exception:
        return []


def _build_stats() -> dict:
    """Compute stats from leads.csv / showcase-style grouping."""
    leads_path = ROOT / "data" / "anomalies" / "conclusions" / "leads.csv"
    adj_path = ROOT / "data" / "anomalies" / "conclusions" / "adjudicated.csv"
    eval_path = ROOT / "data" / "anomalies" / "analysis" / "evaluated.csv"
    catalog_path = ROOT / "data" / "catalog" / "catalog.csv"
    audit_path = ROOT / "data" / "anomalies" / "audit.jsonl"
    marked = ROOT / "data" / "anomalies" / "marked"
    processed = ROOT / "data" / "processed"

    leads = _safe_read_csv(leads_path)
    adj = _safe_read_csv(adj_path)
    catalog = _safe_read_csv(catalog_path)

    verdicts: dict[str, int] = {}
    bodies: dict[str, int] = {}
    bands: dict[str, int] = {}
    for r in leads:
        v = r.get("verdict", "UNKNOWN")
        verdicts[v] = verdicts.get(v, 0) + 1
        # infer bodies/bands from path/image
        img = r.get("image", "")
        path = r.get("path", "")
        body = "Mars" if "mars" in path.lower() or "ESP_" in img else ("Moon" if "moon" in path.lower() or img.startswith("M") else "")
        if body:
            bodies[body] = bodies.get(body, 0) + 1
        for band in ("MIRB", "MRGB", "RED"):
            if f"_{band}." in img:
                bands[band] = bands.get(band, 0) + 1

    marked_count = 0
    if marked.is_dir():
        marked_count = len([p for p in marked.iterdir() if p.suffix.lower() == ".png"])

    sources_count = 0
    if processed.is_dir():
        sources_count = len(list(processed.rglob("*.png"))) + len(list(processed.rglob("*.jpg"))) + len(list(processed.rglob("*.jpeg")))

    audit = _safe_read_jsonl(audit_path, limit=20)
    catalog_rows = len(catalog)

    return {
        "leads_total": len(leads),
        "features": len(leads),  # prior to grouping, showcase groups into ~8599; we report raw here + grouped elsewhere
        "adjudicated_total": len(adj),
        "verdicts": verdicts,
        "bodies": bodies,
        "bands": bands,
        "marked": marked_count,
        "sources": sources_count,
        "catalog_rows": catalog_rows,
        "audit_recent": audit,
        "evaluated_total": len(_safe_read_csv(eval_path)),
    }


# ---------------------------------------------------------------------------
# Analysis helper: reuse pipeline modules in-process (like discord_bot.py)
# ---------------------------------------------------------------------------

def run_image_analysis(image_bytes: bytes, filename: str = "upload.png",
                       max_pixels: int = 4_000_000) -> dict:
    """Analyze raw image bytes with detect + analyze pipeline (in-memory)."""
    import analyze

    # Lazy imports to keep server startup fast
    import detect
    import numpy as np
    from PIL import Image, ImageDraw

    # Decode & downscale
    im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if im.width * im.height > max_pixels:
        k = (max_pixels / float(im.width * im.height)) ** 0.5
        im = im.resize((max(8, int(im.width * k)), max(8, int(im.height * k))), Image.BILINEAR)
    arr = np.asarray(im.convert("L"), dtype=np.float32)

    cands = detect.analyze_array(arr, scales=[1, 2, 4], z=3.0, min_size=12,
                                 max_scale_pixels=12_000_000, path=filename)

    if not cands:
        return {
            "candidates": 0,
            "top": [],
            "message": "No anomalies above threshold. Expected for most imagery.",
            "marked_b64": None,
            "strip_b64": None,
        }

    # Evaluate top candidates
    evaluated = []
    for row in cands:
        crop, feats = analyze.analyze_candidate(row, arr, max_crop=256)
        flags = analyze.artifact_flags(feats)
        score = analyze.interest_score(feats, flags, 0)
        cls = analyze.evidence_class(flags, 0)
        evaluated.append({
            "score": score, "row": row, "feats": feats,
            "flags": flags, "cls": cls, "crop": crop
        })
    evaluated.sort(key=lambda x: x["score"], reverse=True)
    top = evaluated[:3]

    # Draw boxes on copy
    marked = im.copy()
    draw = ImageDraw.Draw(marked)
    for e in top:
        x, y, w, h = e["row"]["x"], e["row"]["y"], e["row"]["w"], e["row"]["h"]
        draw.rectangle([x, y, x + w, y + h], outline=(255, 32, 32), width=2)
        draw.text((x, max(0, y - 12)), f"{e['score']:.0f}%", fill=(255, 32, 32))
    buf = io.BytesIO()
    marked.save(buf, format="PNG")
    marked_b64 = base64.b64encode(buf.getvalue()).decode()

    # Enhancement strip for #1
    strip_b64 = None
    if top:
        variants = analyze.enhance_variants(top[0]["crop"])
        strip_img = analyze.make_strip(variants)
        buf2 = io.BytesIO()
        strip_img.save(buf2, format="JPEG", quality=90)
        strip_b64 = base64.b64encode(buf2.getvalue()).decode()

    top_json = []
    for e in top:
        top_json.append({
            "score": e["score"],
            "cls": e["cls"],
            "verdict": analyze.verdict_text(e["flags"], e["cls"], 0),
            "flags": list(e["flags"].keys()),
            "flags_detail": e["flags"],
            "feats": e["feats"],
            "box": e["row"],
        })

    return {
        "candidates": len(cands),
        "top": top_json,
        "marked_b64": marked_b64,
        "strip_b64": strip_b64,
        "all_boxes": cands[:50],
    }


# ---------------------------------------------------------------------------
# FastAPI app (preferred)
# ---------------------------------------------------------------------------

def create_fastapi_app():
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI, File, HTTPException, Request, UploadFile
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        return None

    app = FastAPI(
        title="NASA Moon & Mars Investigation — Full Stack",
        description="Acquire, catalog, enhance, analyze & adjudicate Moon/Mars imagery. Full pipeline + dashboard in one EXE.",
        version="1.0.95",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- health ----
    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "root": str(ROOT),
            "has_data": (ROOT / "data").exists(),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @app.get("/api/stats")
    def stats():
        return _build_stats()

    @app.get("/api/features")
    def features(limit: int = 50, offset: int = 0, verdict: str | None = None,
                 q: str | None = None, sort: str = "score"):
        leads_path = ROOT / "data" / "anomalies" / "conclusions" / "leads.csv"
        rows = _safe_read_csv(leads_path)
        if verdict:
            rows = [r for r in rows if r.get("verdict") == verdict]
        if q:
            ql = q.lower()
            rows = [r for r in rows if ql in json.dumps(r).lower()]
        # sort
        if sort == "score":
            rows.sort(key=lambda r: float(r.get("score", 0) or 0), reverse=True)
        elif sort == "contrast":
            rows.sort(key=lambda r: float(r.get("contrast", 0) or 0), reverse=True)
        elif sort == "area":
            rows.sort(key=lambda r: int(r.get("area_px", 0) or 0), reverse=True)
        total = len(rows)
        sliced = rows[offset: offset + limit]
        return {"total": total, "limit": limit, "offset": offset, "rows": sliced}

    @app.get("/api/audit")
    def audit(limit: int = 100):
        path = ROOT / "data" / "anomalies" / "audit.jsonl"
        return {"audit": _safe_read_jsonl(path, limit=limit)}

    @app.get("/api/catalog")
    def catalog(limit: int = 100, offset: int = 0):
        path = ROOT / "data" / "catalog" / "catalog.csv"
        rows = _safe_read_csv(path)
        total = len(rows)
        return {"total": total, "rows": rows[offset: offset + limit]}

    @app.post("/api/analyze")
    async def analyze_upload(file: UploadFile = File(...)):
        try:
            data = await file.read()
            if len(data) > 30 * 1024 * 1024:
                raise HTTPException(status_code=413, detail="File too large (max 30 MB)")
            result = run_image_analysis(data, filename=file.filename or "upload.png")
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/pipeline/run")
    async def pipeline_run(request: Request):
        """Trigger pipeline steps in-process (async thread)."""
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass
        step_from = body.get("from", "enhance")
        step_to = body.get("to", "adjudicate")
        query = body.get("query", "moon")

        # Run in background thread so request returns quickly
        def _run():
            try:
                # Build argparse-like object
                class A:
                    start = step_from
                    end = step_to
                    query = query
                    raw = body.get("raw", "data/raw")
                    no_enhance_flags = False
                    selftest = False
                # monkey-patch run_pipeline.MODULES flow manually
                from run_pipeline import MODULES, STEPS, run, step_args
                start_i = STEPS.index(step_from) if step_from in STEPS else 3
                end_i = STEPS.index(step_to) if step_to in STEPS else len(STEPS) - 1
                for s in STEPS[start_i: end_i + 1]:
                    if s == "verify":
                        continue  # skip network-heavy steps in API mode
                    if s == "download" or s == "catalog":
                        continue
                    aobj = A()
                    argv = step_args(s, aobj)
                    rc = run(MODULES[s].main, argv)
                    if rc:
                        break
            except Exception:
                traceback.print_exc()

        th = threading.Thread(target=_run, daemon=True)
        th.start()
        return {"started": True, "from": step_from, "to": step_to, "query": query}

    @app.post("/api/showcase/rebuild")
    def rebuild_showcase():
        try:
            import build_showcase
            build_showcase.main()
            return {"ok": True, "showcase": str(ROOT / "showcase" / "index.html")}
        except Exception as e:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/showcase/data")
    def showcase_data():
        """Return the embedded showcase DATA payload dynamically (no need to prebuild)."""
        # Try to build payload on the fly by invoking build_showcase logic or reading showcase/index.html
        showcase_html = ROOT / "showcase" / "index.html"
        if showcase_html.exists():
            text = showcase_html.read_text(encoding="utf-8", errors="replace")
            # Extract const DATA = {...};  - first occurrence
            import re
            m = re.search(r'const DATA\s*=\s*(\{.*?\});', text, re.S)
            if m:
                try:
                    # The showcase JSON is already a JS object; try to parse as JSON
                    blob = m.group(1)
                    # Replace escaped </
                    data = json.loads(blob.replace("<\\/", "</"))
                    return data
                except Exception:
                    pass
        # Fallback: build minimal stats
        return {"stats": _build_stats(), "features": [], "findings": [], "sources": [], "marked": []}

    # ---- static mounts ----
    # app/static (new full-stack dashboard)
    static_dir = ROOT / "app" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static-app")
    # showcase static (img/, index.html)
    showcase_dir = ROOT / "showcase"
    if showcase_dir.exists():
        app.mount("/showcase", StaticFiles(directory=str(showcase_dir), html=True), name="showcase")
    # data mounts (read-only)
    data_dir = ROOT / "data"
    if data_dir.exists():
        app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")

    # ---- root: serve the full-stack dashboard, fallback to showcase ----
    @app.get("/", response_class=HTMLResponse)
    def root():
        # Prefer new dashboard
        dash = ROOT / "app" / "static" / "index.html"
        if dash.exists():
            return dash.read_text(encoding="utf-8", errors="replace")
        sh = ROOT / "showcase" / "index.html"
        if sh.exists():
            return sh.read_text(encoding="utf-8", errors="replace")
        return HTMLResponse("<h1>NASA Investigation</h1><p>No frontend found. API at /api/health, /api/docs</p>")

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard():
        return root()

    return app


# ---------------------------------------------------------------------------
# stdlib fallback server (when FastAPI not installed)
# ---------------------------------------------------------------------------

def run_stdlib_server(host: str = "127.0.0.1", port: int = 8000):
    import http.server
    import socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/health":
                self.send_json({"status": "ok", "root": str(ROOT)})
                return
            if parsed.path == "/api/stats":
                self.send_json(_build_stats())
                return
            if parsed.path == "/api/audit":
                self.send_json({"audit": _safe_read_jsonl(ROOT / "data" / "anomalies" / "audit.jsonl")})
                return
            if parsed.path in ("/", "/dashboard", "/index.html"):
                dash = ROOT / "app" / "static" / "index.html"
                target = dash if dash.exists() else (ROOT / "showcase" / "index.html")
                if target.exists():
                    self.send_file(target, "text/html")
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(b"<h1>NASA Investigation</h1><p>API at /api/health</p>")
                return
            # serve showcase / data statically
            # map /showcase/* -> showcase/* , /data/* -> data/*
            if parsed.path.startswith("/showcase/") or parsed.path.startswith("/data/") or parsed.path.startswith("/static/"):
                # translate to filesystem
                rel = parsed.path.lstrip("/")
                fs = ROOT / rel
                if fs.is_dir():
                    fs = fs / "index.html"
                if fs.exists() and fs.is_file():
                    ctype = "text/html" if fs.suffix == ".html" else ("application/json" if fs.suffix == ".json" else "application/octet-stream")
                    self.send_file(fs, ctype)
                    return
            self.send_error(404, "Not found")

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/analyze":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length else b""
                # naive multipart parse fallback - just treat body as image bytes if not multipart
                if b"multipart/form-data" in self.headers.get("Content-Type", "").encode():
                    # very naive: extract file bytes between headers and boundary
                    # For robustness, return error asking to use FastAPI mode
                    self.send_json({"error": "multipart requires FastAPI. Install fastapi+uvicorn or POST raw bytes."}, 400)
                    return
                try:
                    result = run_image_analysis(body, filename="upload.png")
                    self.send_json(result)
                except Exception as e:
                    self.send_json({"error": str(e)}, 500)
                return
            self.send_error(404, "Not found")

        def send_json(self, obj, code=200):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def send_file(self, path: Path, ctype: str):
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            sys.stdout.write("%s - - [%s] %s\n" % (self.client_address[0],
                                                     self.log_date_time_string(),
                                                     format % args))

    with socketserver.TCPServer((host, port), Handler) as httpd:
        print(f"Serving stdlib fallback at http://{host}:{port}/  (install fastapi+uvicorn for full API)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


# ---------------------------------------------------------------------------
# main entry for uvicorn / fallback
# ---------------------------------------------------------------------------

def run(host: str = "127.0.0.1", port: int = 8000, reload: bool = False):
    app = create_fastapi_app()
    if app is not None:
        try:
            import uvicorn
            print(f"Starting full-stack server at http://{host}:{port}/  (docs at http://{host}:{port}/docs)")
            print(f"Project root: {ROOT}")
            uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")
            return
        except Exception as e:
            print(f"FastAPI/uvicorn failed ({e}), falling back to stdlib server", file=sys.stderr)
            traceback.print_exc()
    run_stdlib_server(host, port)
