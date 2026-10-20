"""Public software documentation presentation; only admins can publish a PDF."""
import os
import uuid
from datetime import UTC, datetime
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from . import auth, config

router = APIRouter(prefix="/api/documentation", tags=["documentation"])
STORE_DIR = config.UPLOADS_DIR / "documentation"
MAX_BYTES = 25 * 1024 * 1024

@router.get("/presentation")
def presentation_metadata():
    path = STORE_DIR / "presentation.pdf"
    if not path.is_file():
        return {"available": False}
    stat = path.stat()
    return {"available": True, "title": "Презентация BuildVision", "size": stat.st_size,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            "url": f"/api/documentation/presentation/file?v={stat.st_mtime_ns}"}

@router.get("/presentation/file")
def presentation_file():
    path = STORE_DIR / "presentation.pdf"
    if not path.is_file():
        raise HTTPException(404, "Презентация ещё не добавлена")
    return FileResponse(path, media_type="application/pdf", filename="BuildVision-presentation.pdf",
        content_disposition_type="inline", headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})

@router.post("/presentation")
async def upload_presentation(file: UploadFile = File(...), current_user=Depends(auth.require_admin)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "Для встроенного просмотра загрузите презентацию в PDF")
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, "Размер PDF не должен превышать 25 МБ")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(400, "Файл не является PDF")
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STORE_DIR / f"{uuid.uuid4().hex}.tmp"
    try:
        temporary.write_bytes(content)
        os.replace(temporary, STORE_DIR / "presentation.pdf")
    finally:
        temporary.unlink(missing_ok=True)
    return presentation_metadata()
