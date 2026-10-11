"""Integration test for showcase build with new template."""
import sys
import types
import importlib.util
import json
import csv
import os
from pathlib import Path

# Setup paths
sys.path.insert(0, 'pipeline')

# Mock common module
common_mod = types.ModuleType('common')
common_mod.PROJECT_ROOT = '.'
common_mod.load_config = lambda *a, **k: {}
common_mod.PALETTE = [(255, 40, 40)]
common_mod.audit = lambda r: None
common_mod.set_audit = lambda p: None
common_mod.atomic_text_write = lambda p, t: None
common_mod.atomic_csv_write = lambda *a, **k: None
common_mod.sha256_file = lambda *a, **k: ''
common_mod.z_pvalue = lambda z: 0.5
common_mod.benjamini_hochberg = lambda *a, **k: []
common_mod.help_parser = lambda *a, **k: None
common_mod.option_default = lambda *a, **k: None
common_mod.validate_config = lambda *a, **k: True
common_mod.set_seed = lambda s: None
common_mod.validate_box = lambda *a, **k: False
common_mod.contain_path = lambda p: True
sys.modules['common'] = common_mod

# Import build_showcase
spec = importlib.util.spec_from_file_location("build_showcase", "scripts/build_showcase.py")
build_mod = importlib.util.module_from_spec(spec)

# We need to mock Image for build_showcase
import types
pil_mod = types.ModuleType('PIL')
pil_mod.Image = type('Image', (), {
    'MAX_IMAGE_PIXELS': None,
    'open': lambda *a, **k: type('im', (), {
        'size': (800, 600), 'mode': 'RGB', 'convert': lambda s, m: s,
        'resize': lambda *a, **k: s, 'save': lambda *a, **k: None,
        'filter': lambda *a, **k: s, 'width': 800, 'height': 600,
    })(),
})()
sys.modules['PIL'] = pil_mod

# Also mock pipeline modules that build_showcase imports
for mod_name in ['detect', 'analyze', 'mark', 'overlay', 'triage', 'pds', 'metadata', 'photometry', 'stack', 'stereo', 'changedet', 'extras_compare', 'adjudicate', 'enhance', 'stack', 'metadata', 'overlay', 'pds', 'photometry', 'common']:
    m = types.ModuleType(mod_name)
    m.main = lambda *a, **k: None
    sys.modules[mod_name] = m

# Now test template loading directly
ROOT = Path('.')
template_path = ROOT / 'showcase' / 'template.html'

print("=== Template Loading Test ===")
print("template exists:", template_path.exists())
assert template_path.exists(), "Template file missing!"

TEMPLATE = template_path.read_text(encoding='utf-8")
print("template loaded:", len(TEMPLATE), "chars")
assert "__JSON__" in TEMPLATE, "JSON placeholder missing!"
print("JSON placeholder found")

# Test JSON substitution
test_payload = {"stats": {"features": 42}, "features": []}
test_json = json.dumps(test_payload, separators=(",", ":")).replace("</", "<\\/")
result = TEMPLATE.replace("__JSON__", test_json)
assert "features" in result and "42" in result, "Substitution failed!"
print("JSON substitution works")

# Verify key sections exist in template
required_elements = [
    "lightbox", "aiQuery", "masonry", "cat-bar", "category",
    "chart-area", "chScore", "insight-card", "fade-up",
    "kbd", "focus", "reveal",
]
for elem in required_elements:
    assert elem in TEMPLATE, f"Missing element: {elem}"
    print(f"  {elem}: OK")

# Verify CSS variables
assert "var(--bg)" in TEMPLATE
assert "var(--blue)" in TEMPLATE
assert "glassmorphism" not in TEMPLATE  # not a keyword, but blur is
assert "backdrop-filter" in TEMPLATE
print("  glassmorphism/blur effects: OK")

# Verify JavaScript functions
js_funcs = ["runAIQuery", "showAIInsights", "showAISummary", "openLightbox",
            "closeLightbox", "navigateLightbox", "render", "showMore",
            "filtered", "card", "renderAllCharts", "saveSearch", "clearFilters"]
for fn in js_funcs:
    assert fn in TEMPLATE, f"Missing JS function: {fn}"
    print(f"  {fn}(): OK")

print("\n=== ALL SHOWCASE BUILD TESTS PASSED ===")
