"""Download YouTube audio locally before handing it to Lavalink."""
import asyncio
import hashlib
import os
from pathlib import Path
import time
from urllib.parse import quote

CACHE_DIR = Path(os.getenv("YTDLP_CACHE_DIR", "/tmp/discord-quote-bot-audio"))
CACHE_TTL_SECONDS = 24 * 60 * 60


def _cache_name(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest() + ".webm"


def _remove_stale_files():
    cutoff = time.time() - CACHE_TTL_SECONDS
    for path in CACHE_DIR.glob("*"):
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)


async def cache_audio(url):
    """Download a stable local copy and return its private dashboard URL."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _remove_stale_files()
    target = CACHE_DIR / _cache_name(url)
    if not target.exists() or target.stat().st_size == 0:
        partial = target.with_suffix(".part")
        partial.unlink(missing_ok=True)
        process = await asyncio.create_subprocess_exec(
            "yt-dlp", "--no-playlist", "--no-warnings", "-f", "bestaudio/best",
            "--force-overwrites", "-o", str(partial), url,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, error = await asyncio.wait_for(process.communicate(), timeout=120)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            raise RuntimeError("yt-dlp timed out while downloading YouTube audio")
        if process.returncode or not partial.exists() or partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(error.decode("utf-8", "replace")[-500:] or "yt-dlp could not download this video")
        partial.replace(target)
    target.touch()
    base = os.getenv("YTDLP_STREAM_BASE", "http://discord-quote-bot:8080").rstrip("/")
    return base + "/internal/audio/" + quote(target.name)
