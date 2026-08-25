import hashlib
import json
import os
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = {"User-Agent": "nasa-investigation/1.0"}


def make_http(url, timeout=120):
    """Open a URL with the project User-Agent; returns the urllib response."""
    return urllib.request.urlopen(urllib.request.Request(url, headers=USER_AGENT), timeout=timeout)


def fetch_json(url, timeout=180):
    """GET a URL and parse the response body as JSON."""
    with make_http(url, timeout) as r:
        return json.load(r)


def file_sha256(path, block=1 << 16):
    """Return the hex SHA-256 of a file, read in `block`-sized chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            c = f.read(block)
            if not c:
                break
            h.update(c)
    return h.hexdigest()


def safe_name(s):
    """Sanitize an arbitrary string into a safe filesystem name (max 120 chars)."""
    cleaned = "".join(c if c.isalnum() or c in "-_." else "_" for c in s).strip("._") or "item"
    return cleaned[:120]


def log(msg, logpath=None):
    """Print `msg`; if `logpath` is given, also append it to that file."""
    print(msg, flush=True)
    if logpath:
        with open(logpath, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


# --------------------------------------------------------------------------
# verified downloads + manifest
# --------------------------------------------------------------------------

def _fetch_once(url, tmp, attempts=3, timeout=120):
    last = None
    for i in range(attempts):
        try:
            with make_http(url, timeout) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    f.write(chunk)
            return "downloaded"
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def download(url, dest, attempts=3, expected_sha=None, manifest=None, source=""):
    """Download with resume-by-hash. Returns a status string.

    - If dest exists and (no expected sha or hash matches): 'exists'.
    - If dest exists but hash mismatches the expected sha: removed and refetched.
    - A completed download appends a provenance record to the manifest JSONL:
      url, file, sha256, bytes, source.
    """
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        if expected_sha is None:
            return "exists"
        if file_sha256(dest) == expected_sha:
            return "exists"
        os.remove(dest)
    tmp = dest + ".part"
    try:
        _fetch_once(url, tmp, attempts)
    except Exception as e:
        for f in (tmp,):
            if os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
        raise e
    os.replace(tmp, dest)
    if manifest:
        append_manifest(manifest, url, dest, file_sha256(dest), os.path.getsize(dest), source)
    return "downloaded"


def append_manifest(path, url, dest, sha, nbytes, source=""):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    rec = {
        "url": url, "file": os.path.abspath(dest), "sha256": sha,
        "bytes": nbytes, "source": source,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, sort_keys=True) + "\n")


def download_many(tasks, workers=8, manifest=None, source=""):
    """Download many (url, dest, expected_sha) tuples in parallel.

    Returns a list of (url, dest, status) results, one per task. Failures
    raise nothing here; the caller inspects the status values.
    """
    results = [None] * len(tasks)

    def work(idx):
        url, dest = tasks[idx][:2]
        expected = tasks[idx][2] if len(tasks[idx]) > 2 else None
        try:
            status = download(url, dest, expected_sha=expected, manifest=manifest, source=source)
            results[idx] = (url, dest, status)
        except Exception as e:
            results[idx] = (url, dest, "error: %s" % e)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, range(len(tasks))))
    return results
