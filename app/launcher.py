"""Launcher for the full-stack EXE: starts server + opens browser.

Usage (dev):
  python app/launcher.py                # http://127.0.0.1:8000, opens browser
  python app/launcher.py --port 3000 --no-browser
  python app/launcher.py --host 0.0.0.0 --port 8000

Frozen (PyInstaller):
  nasa-fullstack.exe
  nasa-fullstack.exe --port 8000 --no-browser

Clicking the EXE in Explorer launches the dashboard and opens the default
browser. Logs go to console + to data/logs/launcher.log next to the exe.
"""
import argparse
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure project root is importable when frozen or dev
THIS = Path(__file__).resolve()

def get_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys.executable).resolve().parent
    return THIS.parents[1]


ROOT = get_root()
# Put pipeline/scripts on path early so server import can find them
for p in (str(ROOT), str(ROOT / "pipeline"), str(ROOT / "scripts"), str(ROOT / "app")):
    if p not in sys.path:
        sys.path.insert(0, p)


def open_browser_delayed(url: str, delay: float = 1.2):
    def _do():
        time.sleep(delay)
        try:
            webbrowser.open(url)
            print(f"[launcher] opened {url}")
        except Exception as e:
            print(f"[launcher] browser open failed: {e}")
    threading.Thread(target=_do, daemon=True).start()


def main(argv=None):
    # Early --cli split: everything after --cli goes to pipeline verbatim (avoids argparse eating --selftest etc)
    raw = sys.argv[1:] if argv is None else list(argv)
    if "--cli" in raw:
        idx = raw.index("--cli")
        extra = [a for a in raw[idx + 1:] if a != "--"]
        import run_pipeline
        sys.argv = ["run_pipeline.py"] + extra
        run_pipeline.main()
        return

    parser = argparse.ArgumentParser(description="NASA Investigation — Full Stack Launcher (API + Dashboard in one EXE)")
    parser.add_argument("--host", default=os.environ.get("NASA_HOST", "127.0.0.1"), help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NASA_PORT", "8000")), help="port (default 8000)")
    parser.add_argument("--no-browser", action="store_true", help="do not open browser")
    parser.add_argument("--reload", action="store_true", help="uvicorn reload (dev only)")
    parser.add_argument("--cli", action="store_true", help="run pipeline CLI instead of server (delegates to run_pipeline)")
    args = parser.parse_args(argv)

    # Banner
    print("=" * 64)
    print(" NASA Moon & Mars Anomaly Investigation — Full Stack EXE")
    print("=" * 64)
    print(f" Root: {ROOT}")
    print(f" Showcase: {ROOT / 'showcase' / 'index.html'}")
    print(f" Data: {ROOT / 'data'}")
    print(f" Config: {ROOT / 'config' / 'pipeline.json'}")
    # Self-test quick check before serving (non-blocking)
    try:
        port_check = args.port
        host = args.host
        url = f"http://{host}:{port_check}/"
        # docs hint
        print(f" API docs: http://{host}:{port_check}/docs")
        print(f" Health:   http://{host}:{port_check}/api/health")
        if not args.no_browser:
            print(f" Opening browser -> {url}")
            open_browser_delayed(url, delay=1.0)
        else:
            print(f" Listening on {url}  (--no-browser)")
        # Hand off to server
        import server  # from app.server
        server.run(host=host, port=port_check, reload=args.reload)
    except KeyboardInterrupt:
        print("\n[launcher] stopped.")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[launcher] fatal: {e}", file=sys.stderr)
        # keep window open when double-clicked
        if getattr(sys, "frozen", False):
            input("Press Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
