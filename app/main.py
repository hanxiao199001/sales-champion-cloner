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

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
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
from app.tasks import process_recording, process_transcript, check_stale_recordings

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
        client.storage.from_(db.AUDIO_BUCKET).upload(storage_path, content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {e}")

    # 私有 bucket：为 ASR 服务生成限时签名 URL（不再使用 public URL）
    audio_url = db.get_audio_url(storage_path)

    # Create recording record
    recording = db.create_recording(
        filename=file.filename or storage_filename,
        storage_path=storage_path,
    )

    # Start async processing
    # TODO(队列化): asyncio.create_task 在进程重启/多 worker 部署时会丢任务，
    # 后续迁移到 arq/celery 持久化任务队列，见 docs/UPGRADE_NOTES.md
    asyncio.create_task(process_recording(recording["id"], audio_url))

    return RedirectResponse(
        url=f"/recording/{recording['id']}", status_code=302
    )


@app.post("/upload-transcript")
async def upload_transcript(
    request: Request,
    title: str = Form(...),
    transcript_text: str = Form(...),
):
    """Semi-auto mode: paste transcript text from recording card, skip ASR entirely."""
    require_auth(request)

    if not transcript_text.strip():
        raise HTTPException(status_code=400, detail="转写文本不能为空")

    # Create recording record (no audio file needed)
    recording = db.create_recording(
        filename=title or "手动导入的转写稿",
        storage_path="manual",
    )

    # Parse transcript into segments (simple line-based format)
    segments = _parse_manual_transcript(transcript_text)

    # Save transcript and go straight to analysis (skip ASR)
    db.update_recording(recording["id"], transcript=segments, asr_confidence=100.0)
    # TODO(队列化): 同上，迁移到 arq/celery，见 docs/UPGRADE_NOTES.md
    asyncio.create_task(process_transcript(recording["id"], segments))

    return RedirectResponse(
        url=f"/recording/{recording['id']}", status_code=302
    )


def _parse_manual_transcript(text: str) -> list[dict]:
    """
    Parse manually pasted transcript into segments.

    Supports formats:
    - "销售: xxx" / "客户: xxx" (labeled)
    - "A: xxx" / "B: xxx" (labeled)
    - Plain text (all attributed to boss)
    """
    lines = text.strip().split("\n")
    segments = []
    boss_labels = {"销售", "老板", "我", "a", "A", "销冠", "经纪人", "业务员"}
    client_labels = {"客户", "顾客", "买家", "b", "B", "客"}

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        speaker = "boss"
        text_content = line

        # Try to detect "label: content" format
        if ":" in line or "：" in line:
            sep = "：" if "：" in line else ":"
            parts = line.split(sep, 1)
            label = parts[0].strip()
            if label in boss_labels:
                speaker = "boss"
                text_content = parts[1].strip()
            elif label in client_labels:
                speaker = "client"
                text_content = parts[1].strip()

        if text_content:
            segments.append(
                {
                    "speaker": speaker,
                    "text": text_content,
                    "start": float(i),
                    "end": float(i + 1),
                }
            )

    return segments


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

    # Get audio URL and restart processing（私有 bucket 签名 URL）
    audio_url = db.get_audio_url(recording["storage_path"])
    # TODO(队列化): 同上，迁移到 arq/celery，见 docs/UPGRADE_NOTES.md
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
