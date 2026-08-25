"""Discord bot: upload an image, get it run through the anomaly pipeline.

It reuses the pipeline modules directly (detect.analyze_array ->
analyze.analyze_candidate -> artifact_flags / interest_score /
evidence_class / verdict_text) and replies with a marked-up image plus a
plain-language verdict for the strongest candidates.

Safety and honesty guards:
- Only raster image attachments (PNG/JPEG/WebP/TIFF/GIF/BMP) are accepted.
- Uploads are capped at ~25 MB and downscaled to MAX_PIXELS before analysis.
- Every reply states the results are preliminary computer vision findings on
  a single image, not confirmed anomalies.
- The pipeline runs in a worker thread (no blocking of the event loop).
- One analysis at a time per bot; extra images are queued.

Setup:
  pip install -r requirements-extras.txt        # brings discord.py
  $env:DISCORD_TOKEN = "..."                    # from Discord Developer Portal
  python bot/discord_bot.py

Standalone test (no Discord account needed):
  python bot/discord_bot.py --analyze path/to/image.png
"""

import argparse
import asyncio
import hashlib
import io
import os
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

import analyze
import detect

MAX_PIXELS = int(os.environ.get("ANOMALY_MAX_PIXELS", "4_000_000"))
MAX_BYTES = int(os.environ.get("ANOMALY_MAX_BYTES", str(25 * 1024 * 1024)))
ALLOWED_TYPES = ("image/png", "image/jpeg", "image/webp", "image/tiff", "image/gif", "image/bmp")
DETECT = {"scales": [1, 2, 4], "z": 3.0, "min_size": 12, "max_scale_pixels": 12_000_000}
MAX_CROP = 256
TOP_N = 3

HELP = (
    "Upload a Moon/Mars image (PNG, JPEG, WebP, TIFF) and I'll run the "
    "anomaly pipeline on it: local-contrast detection, artifact triage, and a "
    "verdict on the strongest candidates. One image per message; up to %d px. "
    "Remember: findings are preliminary and single-image — not confirmations."
    % MAX_PIXELS
)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _downscale(img):
    if img.width * img.height <= MAX_PIXELS:
        return img
    k = (MAX_PIXELS / float(img.width * img.height)) ** 0.5
    return img.resize((max(8, int(img.width * k)), max(8, int(img.height * k))), Image.BILINEAR)


def run_analysis(image_bytes, name="upload", out_dir=None):
    """Analyze raw image bytes. Returns (summary_text, marked_path, strip_path)."""
    ws = out_dir or tempfile.mkdtemp(prefix="anomaly_bot_")
    os.makedirs(ws, exist_ok=True)
    img = _downscale(Image.open(io.BytesIO(image_bytes)).convert("RGB"))
    arr = np.asarray(img.convert("L"), dtype=np.float32)

    cands = detect.analyze_array(arr, **DETECT, path=name)
    if not cands:
        return ("No anomalies above the detection threshold were found in this "
                "image. That is the expected result for most imagery.",
                None, None)

    marked = img.copy()
    draw = ImageDraw.Draw(marked)
    evaluated = []
    for row in cands:
        crop, feats = analyze.analyze_candidate(row, arr, MAX_CROP)
        flags = analyze.artifact_flags(feats)
        score = analyze.interest_score(feats, flags, 0)
        cls = analyze.evidence_class(flags, 0)
        evaluated.append((score, row, feats, flags, cls, crop))

    evaluated.sort(key=lambda t: t[0], reverse=True)
    top = evaluated[:TOP_N]

    for score, row, feats, flags, cls, crop in top:
        x, y, w, h = row["x"], row["y"], row["w"], row["h"]
        draw.rectangle([x, y, x + w, y + h], outline=(255, 32, 32), width=2)
        draw.text((x, max(0, y - 12)), "%.0f%%" % score, fill=(255, 32, 32))

    marked_path = os.path.join(ws, "marked.png")
    marked.save(marked_path)

    strip_path = None
    if top:
        variants = analyze.enhance_variants(top[0][5])
        strip_img = analyze.make_strip(variants)
        strip_path = os.path.join(ws, "top_strip.png")
        strip_img.save(strip_path)

    lines = ["**%d candidate(s) above threshold** (preliminary, single-image):" % len(cands)]
    for i, (score, row, feats, flags, cls, crop) in enumerate(top, 1):
        verdict = analyze.verdict_text(flags, cls, 0)
        lines.append(
            "**#%d — score %.1f/100**  (%d,%d  %dx%d px, %s, contrast %.2f)\n"
            "> %s" % (i, score, row["x"], row["y"], row["w"], row["h"],
                      feats["polarity"], feats["contrast"], verdict))
    lines.append("_Computer-vision findings only. Verify against the raw "
                 "archive product and an independent pass before believing "
                 "anything._")
    return "\n".join(lines), marked_path, strip_path


def make_discord_bot():
    try:
        import discord
    except ImportError as e:
        raise SystemExit("discord.py is not installed. Run: pip install -r "
                         "requirements-extras.txt  (%s)" % e)

    intents = discord.Intents.default()
    intents.message_content = True

    class AnomalyBot(discord.Client):
        def __init__(self, *args, **kwargs):
            super().__init__(intents=intents, *args, **kwargs)
            self._sem = asyncio.Semaphore(1)

        async def on_ready(self):
            print("logged in as", self.user)

        async def on_message(self, message):
            if message.author.bot:
                return
            if message.attachments:
                await self.handle_upload(message)

        async def handle_upload(self, message):
            async with self._sem:
                attach = message.attachments[0]
                if attach.content_type not in ALLOWED_TYPES and attach.filename.lower().split(".")[-1] not in (
                        "png", "jpg", "jpeg", "webp", "tif", "tiff"):
                    await message.channel.send("That file doesn't look like a "
                                               "supported image type. " + HELP)
                    return
                if attach.size > MAX_BYTES:
                    await message.channel.send("Image too large (max ~25 MB).")
                    return
                async with message.channel.typing():
                    data = await attach.read()
                if len(data) > MAX_BYTES:
                    await message.channel.send("Image too large (max ~25 MB).")
                    return
                ws = os.path.join(ROOT, "data", "bot", str(message.id))
                loop = asyncio.get_running_loop()
                try:
                    text, marked, strip = await loop.run_in_executor(
                        None, run_analysis, data, attach.filename, ws)
                except Exception as e:
                    await message.channel.send("Analysis failed: %s" % e)
                    return
                files = []
                if marked:
                    files.append(discord.File(marked, filename="marked.png"))
                if strip:
                    files.append(discord.File(strip, filename="top_candidate_strip.png"))
                if len(text) > 1990:
                    text = text[:1990] + "…"
                await message.channel.send(text, files=files or None)

    return AnomalyBot()


def main():
    p = argparse.ArgumentParser(description="Anomaly-pipeline Discord bot (or standalone analyzer)")
    p.add_argument("--analyze", metavar="IMAGE", help="run the pipeline on a local image and print results (no Discord)")
    a = p.parse_args()

    if a.analyze:
        with open(a.analyze, "rb") as f:
            data = f.read()
        text, marked, strip = run_analysis(data, name=os.path.basename(a.analyze))
        print(text)
        print("marked:", marked)
        print("strip:", strip)
        return

    token = os.environ.get("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN not set. Export it (see bot docstring).")
    bot = make_discord_bot()
    bot.run(token)


if __name__ == "__main__":
    main()
