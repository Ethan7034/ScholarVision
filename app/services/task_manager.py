"""
Layer 5 queue -- asynchronous job management.

What v1.0 did wrong
  /api/analyze waited for the VLM inside the request cycle, so the frontend
  fake-progressed with setInterval playing seven canned log lines. Real
  duration stayed unknown, and long papers risked tunnel timeouts.

v2.0 design
  Submit -> return job_id immediately -> execute as a background asyncio task
  -> persist status and progress to Redis -> frontend polls
  /api/tasks/{job_id} for real progress.

v2.1 design (dual-mode execution)
  - Redis reachable: jobs go into sv:queue:analyze and a standalone
    worker.py process executes them. The API process keeps doing only
    authentication, caching, and enqueueing; long model calls live entirely
    outside it. A crashed worker leaves payloads in the processing list,
    recoverable at startup, so nothing is lost.
  - Redis unreachable: automatically falls back to v2.0 in-process asyncio
    execution. The project must not hard-depend on Redis; the plain
    "pip install, then uvicorn" development path has to keep working.

Known limits (stated explicitly)
  - Cross-process progress writes the job record directly (no in-memory
    merge); one Redis read per poll suffices.
  - In-process mode loses in-flight jobs on API restart. In worker mode,
    processing-list reclamation runs once per worker startup. Multiple
    workers consuming the same queue is safe (BRPOPLPUSH pops atomically),
    though a single worker is plenty at current scale.
"""

import asyncio
import json
import os
import re
import shutil
import time
import uuid

from app.core.config import settings
from app.core.logging import logger
from app.core.store import analyze_key, job_key, store
from app.services.agent import orchestrate_analysis_async

UPLOAD_DIR = "uploads"
JOB_TTL = 60 * 60  # 任务状态保留 1 小时

# 进程内模式（无 Redis 兜底）的运行中任务，供优雅关闭时取消
_INPROCESS: dict[str, asyncio.Task] = {}


def sanitize_filename(filename: str) -> str:
    """Keep only safe characters and drop path separators.

    v1.0 built temp paths by interpolating client-controlled filenames, which
    allowed traversal (../../) and concurrent same-name overwrites.
    """
    name = os.path.basename(filename or "").strip()
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[-100:] or "unnamed.pdf"


def _safe_storage_name(original: str) -> str:
    """随机前缀，保证并发上传不互相覆盖。"""
    return f"{uuid.uuid4().hex[:8]}_{sanitize_filename(original)}"


def _save_history(user_id: int | None, filename: str, result: dict) -> None:
    """Persist an analysis to PaperHistory.

    v1.0 defined this table but never wrote a single row; the history feature
    was a stub. Synchronous SQLAlchemy write -- callers run it in a thread
    pool so the event loop stays free.
    """
    if user_id is None:
        return
    from app.models.database import PaperHistory, SessionLocal

    db = SessionLocal()
    try:
        db.add(
            PaperHistory(
                user_id=user_id,
                filename=filename,
                vlm_result=result.get("vlm_result", "")[:20000],
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning(f"历史记录写入失败: {type(exc).__name__} - {exc}")
    finally:
        db.close()


# ----------------------------------------------------------------------
# Execution body (shared by in-process mode and the worker process)
# ----------------------------------------------------------------------
async def write_job(job_id: str, **fields) -> None:
    """Read-modify-write the job record; the only progress channel that
    survives the process boundary in queue mode."""
    job = await store.get_json(job_key(job_id)) or {"job_id": job_id}
    job.update(fields)
    job["updated_at"] = time.time()
    await store.set_json(job_key(job_id), job, ttl=JOB_TTL)


async def execute_job(
    job_id: str,
    pdf_path: str,
    filename: str,
    file_hash: str,
    out_dir: str,
    user_id: int | None = None,
) -> None:
    """Parse + concurrent VLM + cache the result + persist history.

    Progress is persisted straight into the job record so a polling API
    process sees it without sharing memory with the executor.
    """

    async def progress_cb(done: int, total: int) -> None:
        # 编排层每张图完成时调用；写 Redis 失败不能拖垮分析本体
        try:
            await write_job(job_id, progress={"done": done, "total": total})
        except Exception:
            pass

    try:
        await write_job(
            job_id,
            status="running",
            filename=filename,
            started_at=time.time(),
            progress={"done": 0, "total": 0},
        )
        logger.info(f"[Job {job_id}] 开始处理: {filename}")

        result = await orchestrate_analysis_async(
            pdf_path, output_dir=out_dir, progress_cb=progress_cb
        )
        result["filename"] = filename

        if result.get("status") == "success":
            # 命中缓存的后续上传可直接秒回，不再消耗模型配额
            await store.set_json(
                analyze_key(file_hash), result, ttl=settings.CACHE_TTL_ANALYZE
            )
            await write_job(
                job_id,
                status="completed",
                result=result,
                progress={
                    "done": result.get("images_total", 0),
                    "total": result.get("images_total", 0),
                },
            )
            # 落库到 PaperHistory（同步 IO 放线程池，不阻塞事件循环）
            await asyncio.to_thread(_save_history, user_id, filename, result)
            logger.info(f"[Job {job_id}] ✅ 完成: {filename}")
        else:
            await write_job(job_id, status="completed", result=result)
            logger.info(f"[Job {job_id}] ⚠️ 完成但无图表: {filename}")

    except asyncio.CancelledError:
        logger.warning(f"[Job {job_id}] 已取消")
        await write_job(job_id, status="cancelled", error="worker/API 关闭，任务已中断")
        raise
    except Exception as exc:
        logger.error(f"[Job {job_id}] ❌ 失败: {type(exc).__name__} - {exc}")
        await write_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
    finally:
        _INPROCESS.pop(job_id, None)
        # 清理临时文件与图片输出目录
        shutil.rmtree(out_dir, ignore_errors=True)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)


async def execute_job_from_payload(payload: str) -> None:
    """Worker consumption entry: decode queue message, run, then ack.

    Ack policy lives here rather than inside worker.py so every consumer
    shares one reliability contract: a normal finish (including a
    business-level failure whose reason is already stored in the job record)
    acknowledges the payload; a cancellation deliberately does not, leaving
    it in the processing list for the next startup's reclaim pass.
    """
    spec = json.loads(payload)
    cancelled = False
    try:
        await execute_job(
            spec["job_id"],
            spec["pdf_path"],
            spec["filename"],
            spec["file_hash"],
            spec["out_dir"],
            spec.get("user_id"),
        )
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        if not cancelled:
            await store.queue_ack(settings.PROCESSING_LIST, payload)


# ----------------------------------------------------------------------
# Submission side (called from the API process)
# ----------------------------------------------------------------------
async def submit_analysis_task(
    file_hash: str, file_bytes: bytes, filename: str, user_id: int | None = None
) -> dict:
    """Save the upload, create a job, and hand it to a Redis queue when one
    exists; otherwise run it in-process. The request cycle stays in
    milliseconds either way.
    """
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored_name = _safe_storage_name(filename)
    pdf_path = os.path.join(UPLOAD_DIR, stored_name)
    out_dir = os.path.join("images", uuid.uuid4().hex[:8])

    with open(pdf_path, "wb") as buffer:
        buffer.write(file_bytes)

    job_id = uuid.uuid4().hex
    await write_job(
        job_id,
        status="queued",
        filename=filename,
        file_hash=file_hash,
        created_at=time.time(),
    )

    payload = json.dumps(
        {
            "job_id": job_id,
            "pdf_path": pdf_path,
            "filename": filename,
            "file_hash": file_hash,
            "out_dir": out_dir,
            "user_id": user_id,
        },
        ensure_ascii=False,
    )

    enqueued = False
    try:
        if await store.queue_available():
            enqueued = await store.queue_push(settings.QUEUE_NAME, payload)
    except Exception as exc:
        logger.warning(f"入队失败，退回进程内执行: {type(exc).__name__} - {exc}")

    if enqueued:
        logger.info(f"📋 任务已入 Redis 队列: {job_id} ({filename})，等待 worker 消费")
    else:
        task = asyncio.create_task(
            execute_job(job_id, pdf_path, filename, file_hash, out_dir, user_id)
        )
        _INPROCESS[job_id] = task
        logger.info(f"📋 任务在 API 进程内执行: {job_id} ({filename})（无 Redis 兜底路径）")

    return {"job_id": job_id, "status": "queued", "filename": filename}


async def get_task_status(job_id: str) -> dict | None:
    """读取任务状态（进度由执行方持久化，跨进程可直接读到）。"""
    return await store.get_json(job_key(job_id))


async def queue_depth() -> int | None:
    """Queue depth for /api/health; None when queue mode is off."""
    try:
        if await store.queue_available():
            return await store.queue_len(settings.QUEUE_NAME)
    except Exception:
        return None
    return None


async def shutdown_tasks() -> None:
    """Cancel all in-flight in-process jobs on shutdown so nothing hangs."""
    for job_id, task in list(_INPROCESS.items()):
        task.cancel()
    if _INPROCESS:
        logger.info(f"🛑 已取消 {len(_INPROCESS)} 个在途分析任务")
        await asyncio.gather(*_INPROCESS.values(), return_exceptions=True)
        _INPROCESS.clear()
