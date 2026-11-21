"""
Layer 3 -- Analysis routes.

API contract change from v1.0 (the frontend was rebuilt around this)
  Old: POST /api/analyze blocked for minutes and returned the final
       AnalysisResponse in the same request.
  New: POST /api/analyze returns {job_id} in milliseconds;
       GET /api/tasks/{job_id} is polled for real progress and the result.

Caching: an upload whose fingerprint already sits in Redis returns
status=completed immediately -- no queue, no model calls, no quota spent.
"""

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_current_user
from app.models.schemas import TaskSubmitResponse
from app.models.database import PaperHistory, get_db
from app.core.store import analyze_key, store
from app.services.task_manager import get_task_status, submit_analysis_task

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 与前端 "Max size: 10MB" 提示对齐


@router.post("/analyze", response_model=TaskSubmitResponse, status_code=202)
async def analyze_paper(
    request: Request,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
):
    """Accept a PDF and return a job id instantly; analysis runs in background."""
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="❌ 只支持上传 PDF 文件")

    file_content = await file.read()
    if not file_content:
        raise HTTPException(status_code=400, detail="❌ 上传文件为空")
    if len(file_content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"❌ 文件超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
        )

    file_hash = hashlib.md5(file_content).hexdigest()

    # 1. 缓存命中：同一份 PDF 直接复用结果，不消耗模型配额
    cached = await store.get_json(analyze_key(file_hash))
    if cached:
        logger.info(f"🎯 缓存命中 {file_hash[:8]}，跳过模型调用")
        return TaskSubmitResponse(
            job_id=None,
            status="completed",
            filename=file.filename,
            cached=True,
            result=cached,
        )

    # 2. 未命中：入队后台执行
    task_info = await submit_analysis_task(
        file_hash, file_content, file.filename, user_id=current_user.id
    )
    return TaskSubmitResponse(
        job_id=task_info["job_id"],
        status="queued",
        filename=file.filename,
        cached=False,
    )


@router.get("/tasks/{job_id}")
async def read_task(job_id: str, request: Request):
    """Poll job state: queued / running (with progress) / completed / failed."""
    job = await get_task_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或状态已过期")
    return job


@router.get("/history")
def list_history(request: Request, db=Depends(get_db), current_user=Depends(get_current_user)):
    """Return the current user's past analyses.

    v1.0 defined the PaperHistory table but never wrote a row, so history was
    a stub; jobs now persist results through the task manager and this route
    serves them back.
    """
    rows = (
        db.query(PaperHistory)
        .filter(PaperHistory.user_id == current_user.id)
        .order_by(PaperHistory.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "status": "success",
        "count": len(rows),
        "items": [
            {
                "id": r.id,
                "filename": r.filename,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
