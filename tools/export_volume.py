"""Temporary authenticated Railway volume exporter used during VPS migration."""
import io
import os
import zipfile
from pathlib import Path

from aiohttp import web


DATA_FILES = ("quotes.json", "names.json", "nicknames.json")


async def export(request: web.Request) -> web.Response:
    if request.match_info["token"] != os.environ["DASHBOARD_TOKEN"]:
        raise web.HTTPNotFound()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in DATA_FILES:
            path = Path("/data") / name
            if path.is_file():
                bundle.write(path, name)
    return web.Response(
        body=archive.getvalue(),
        content_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="discord-bot-data.zip"'},
    )


app = web.Application()
app.router.add_get("/{token}/export.zip", export)
web.run_app(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")), access_log=None)
