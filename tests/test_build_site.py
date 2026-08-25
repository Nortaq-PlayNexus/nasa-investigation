import sys
import tempfile
from collections import Counter
from pathlib import Path

from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import build_site as bs  # noqa: E402


def test_crop_box_centers_feature():
    im = Image.new("RGB", (200, 100), (10, 10, 10))
    for xx in range(90, 110):
        for yy in range(40, 60):
            im.putpixel((xx, yy), (240, 240, 240))
    p = Path(tempfile.NamedTemporaryFile(suffix=".jpg", delete=False).name)
    im.save(p)
    try:
        cb = bs.crop_box(p, 100, 50, 20, 20)
        assert cb is not None
        assert all(0.0 <= v <= 1.0 for v in cb)
        assert cb[2] > 0 and cb[3] > 0
        assert abs((cb[0] + cb[2] / 2) - 0.5) < 0.05
    finally:
        p.unlink(missing_ok=True)


def test_crop_box_missing_file():
    assert bs.crop_box(Path("does_not_exist.jpg"), 1, 1, 2, 2) is None


def test_dedupe_collapses_and_keeps_best():
    rows = [
        {"image": "ESP_013236_1410_MIRB.abrowse_enh.png", "verdict": "CONFIRMED-LEAD", "score": "80", "x": "5", "y": "5", "w": "10", "h": "10", "contrast": "2"},
        {"image": "ESP_013236_1410_RED.browse_enh.png", "verdict": "CONFIRMED-LEAD", "score": "100", "x": "5", "y": "5", "w": "10", "h": "10", "contrast": "2"},
        {"image": "ESP_013948_1410_RED.browse_enh.png", "verdict": "CONFIRMED-LEAD", "score": "90", "x": "9", "y": "9", "w": "10", "h": "10", "contrast": "2"},
    ]
    dd = bs.dedupe(rows)
    assert len(dd) == 2
    kept = [r for r in dd if r["image"].startswith("ESP_013236_1410")][0]
    assert kept["score"] == "100"


def test_diverse_preview_spreads_and_caps():
    big = [
        {"image": f"IMG_{i % 3}.png", "verdict": "CONFIRMED-LEAD", "score": str(i),
         "x": "1", "y": "1", "w": "4", "h": "4", "contrast": "2"}
        for i in range(20)
    ]
    prev = bs.diverse_preview(big, 6, 2)
    cnt = Counter(r["image"] for r in prev)
    assert len(prev) == 6
    assert all(v <= 2 for v in cnt.values())


def test_verdict_counts():
    rows = [{"image": "a", "verdict": "CONFIRMED-LEAD"}] * 3
    assert bs.verdict_counts(rows).get("CONFIRMED-LEAD", 0) == 3
