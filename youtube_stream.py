"""Stream YouTube audio through yt-dlp for Lavalink."""
import asyncio
import os
from urllib.parse import urlencode


def stream_url(url):
    """Internal URL Lavalink uses; yt-dlp owns the actual YouTube connection."""
    base = os.getenv("YTDLP_STREAM_BASE", "http://discord-quote-bot:8080")
    return base.rstrip("/") + "/internal/audio?" + urlencode({"url": url})


async def start_audio_stream(url):
    """Start yt-dlp writing a fresh best-audio stream to stdout."""
    process = await asyncio.create_subprocess_exec(
        "yt-dlp", "--no-playlist", "--no-warnings", "-f", "bestaudio/best", "-o", "-", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    return process
