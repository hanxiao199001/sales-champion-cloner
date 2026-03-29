"""
Sales Champion Cloner — Phase A (销冠镜子)

A tool for extracting sales patterns from a top performer's call recordings.
Single-user, password-protected, async processing.
"""

import asyncio
import os
import uuid
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app import database as db
from app.config import (
    APP_PASSWORD,
    AUDIO_EXTENSIONS,
    MAX_FILE_SIZE_MB,
    PLAYBOOK_MIN_RECORDINGS,
)
from app.models import RecordingStatus, RETRYABLE_STATUSES
from app.tasks import process_recording, check_stale_recordings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def periodic_stale_check():
    """Background loop to detect stuck recordings every 60 seconds."""
    while True:
        try:
            count = await check_stale_recordings()
            if count:
                logger.info(f"Marked {count} stale recording(s) as failed")
        except Exception as e:
            logger.error(f"Stale check error: {e}")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(periodic_stale_check())
    yield
    task.cancel()


app = FastAPI(title="Sales Champion Cloner", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.urandom(32).hex())

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
)


def require_auth(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not authenticated")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if request.session.get("authenticated"):
        return RedirectResponse(url="/recordings", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
async def login(request: Request, password: str = Form(...)):
    if password == APP_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/recordings", status_code=302)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": "密码错误"}
    )


@app.get("/recordings", response_class=HTMLResponse)
async def list_recordings(request: Request):
    require_auth(request)
    recordings = db.list_recordings()
    return templates.TemplateResponse(
        "recordings.html", {"request": request, "recordings": recordings}
    )


@app.post("/upload")
async def upload_recording(request: Request, file: UploadFile = File(...)):
    require_auth(request)

    # Validate file extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式 {ext}。支持的格式: {', '.join(AUDIO_EXTENSIONS)}",
        )

    # Read and check file size
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"文件太大 ({size_mb:.1f}MB)。最大支持 {MAX_FILE_SIZE_MB}MB。",
        )

    # Upload to Supabase Storage
    storage_filename = f"{uuid.uuid4().hex}{ext}"
    storage_path = f"recordings/{storage_filename}"

    try:
        client = db.get_client()
        client.storage.from_("audio").upload(storage_path, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}")

    # Get public URL for ASR service
    audio_url = client.storage.from_("audio").get_public_url(storage_path)

    # Create recording record
    recording = db.create_recording(
        filename=file.filename or storage_filename,
        storage_path=storage_path,
    )

    # Start async processing
    asyncio.create_task(process_recording(recording["id"], audio_url))

    return RedirectResponse(
        url=f"/recording/{recording['id']}", status_code=302
    )


@app.get("/recording/{recording_id}", response_class=HTMLResponse)
async def view_recording(request: Request, recording_id: str):
    require_auth(request)
    recording = db.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="录音不存在")
    return templates.TemplateResponse(
        "recording.html", {"request": request, "recording": recording}
    )


@app.get("/api/recording/{recording_id}/status")
async def recording_status(request: Request, recording_id: str):
    """Polling endpoint for async status updates."""
    require_auth(request)
    recording = db.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404)
    return JSONResponse(
        {
            "status": recording["status"],
            "error_message": recording.get("error_message"),
        }
    )


@app.post("/recording/{recording_id}/retry")
async def retry_recording(request: Request, recording_id: str):
    require_auth(request)
    recording = db.get_recording(recording_id)
    if not recording:
        raise HTTPException(status_code=404, detail="录音不存在")

    if recording["status"] not in {s.value for s in RETRYABLE_STATUSES}:
        raise HTTPException(status_code=400, detail="只有失败的录音才能重试")

    # Reset status and clear error
    db.update_recording(
        recording_id,
        status=RecordingStatus.UPLOADED.value,
        error_message=None,
    )

    # Get audio URL and restart processing
    client = db.get_client()
    audio_url = client.storage.from_("audio").get_public_url(recording["storage_path"])
    asyncio.create_task(process_recording(recording_id, audio_url))

    return RedirectResponse(
        url=f"/recording/{recording_id}", status_code=302
    )


@app.get("/playbook", response_class=HTMLResponse)
async def view_playbook(request: Request):
    require_auth(request)
    patterns = db.get_playbook_patterns()
    completed_count = len(db.get_completed_recordings())
    min_required = PLAYBOOK_MIN_RECORDINGS
    return templates.TemplateResponse(
        "playbook.html",
        {
            "request": request,
            "patterns": patterns,
            "completed_count": completed_count,
            "min_required": min_required,
        },
    )


if __name__ == "__main__":
    import uvicorn
    from app.config import APP_HOST, APP_PORT

    uvicorn.run("app.main:app", host=APP_HOST, port=APP_PORT, reload=True)
