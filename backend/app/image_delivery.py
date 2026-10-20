"""Authenticated image delivery with reusable display copies and conditional requests."""

import hashlib
import os
import tempfile
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse
from PIL import Image

from . import config


def image_response(path: Path, request: Request, *, preview: bool = False) -> Response:
    stat = path.stat()
    key = hashlib.sha256(
        f"webp-v1:{path}:{stat.st_mtime_ns}:{stat.st_size}".encode()
    ).hexdigest()
    etag = f'"{key}-{"preview" if preview else "original"}"'
    headers = {"Cache-Control": "private, no-cache", "ETag": etag, "Vary": "Cookie"}
    if etag in [
        tag.strip() for tag in request.headers.get("if-none-match", "").split(",")
    ]:
        return Response(status_code=304, headers=headers)
    target = path
    if preview:
        cache = config.UPLOADS_DIR / "image_previews"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / f"{key}.webp"
        if not target.exists():
            temp = None
            try:
                with Image.open(path) as image:
                    # Keep the original pixel geometry: detector coordinates must remain valid.
                    orientation = image.getexif().get(274)
                    exif = Image.Exif()
                    if orientation is not None:
                        exif[274] = orientation
                    image = image.convert("RGB")
                    with tempfile.NamedTemporaryFile(
                        dir=cache, suffix=".webp", delete=False
                    ) as handle:
                        temp = Path(handle.name)
                    image.save(temp, "WEBP", quality=82, method=4, exif=exif)
                os.replace(temp, target)
            except (OSError, ValueError):
                target = path
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
    return FileResponse(target, headers=headers)
