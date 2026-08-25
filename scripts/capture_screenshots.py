"""Capture screenshots for repository documentation."""
import os
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "screenshots")
os.makedirs(OUT, exist_ok=True)

PAGES = [
    ("dashboard.png", "file:///" + os.path.join(ROOT, "app", "static", "index.html").replace("\\", "/"), 1280, 800),
    ("showcase.png", "file:///" + os.path.join(ROOT, "showcase", "index.html").replace("\\", "/"), 1280, 800),
    ("triage.png", "file:///" + os.path.join(ROOT, "data", "anomalies", "triage", "index.html").replace("\\", "/"), 1280, 800),
    ("report.png", "file:///" + os.path.join(ROOT, "data", "anomalies", "analysis", "report.html").replace("\\", "/"), 1280, 2000),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    for name, url, width, height in PAGES:
        path = os.path.join(OUT, name)
        if not os.path.exists(os.path.dirname(os.path.join(ROOT, "data", "anomalies", "triage"))):
            print(f"  SKIP {name} (data not generated yet)")
            continue
        try:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=10000)
            page.screenshot(path=path, full_page=False)
            page.close()
            print(f"  OK   {name}")
        except Exception as e:
            print(f"  FAIL {name}: {e}")
    browser.close()
