import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import _common as c  # noqa: E402


def test_safe_name():
    assert c.safe_name("ESP_013236_1410_MIRB.abrowse_enh.png") == "ESP_013236_1410_MIRB.abrowse_enh.png"
    assert c.safe_name("../../etc/passwd") == "etc_passwd"
    assert c.safe_name("") == "item"
    assert len(c.safe_name("a" * 500)) <= 120


def test_file_sha256():
    data = b"hello hirise"
    p = Path(tempfile.NamedTemporaryFile(delete=False).name)
    p.write_bytes(data)
    try:
        assert c.file_sha256(p) == hashlib.sha256(data).hexdigest()
    finally:
        p.unlink(missing_ok=True)
