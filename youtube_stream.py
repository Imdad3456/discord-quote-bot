"""Resolve YouTube videos to short-lived audio URLs with yt-dlp."""
import asyncio


async def audio_url(url):
    """Return a signed best-audio URL suitable for Lavalink's HTTP source."""
    process = await asyncio.create_subprocess_exec(
        "yt-dlp", "--no-playlist", "--no-warnings", "-f", "bestaudio/best", "-g", url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), timeout=45)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise RuntimeError("yt-dlp timed out while preparing YouTube audio")
    if process.returncode or not output.strip():
        raise RuntimeError(error.decode("utf-8", "replace")[-500:] or "yt-dlp could not prepare this video")
    return output.decode("utf-8", "replace").splitlines()[0]
