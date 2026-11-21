"""
Scholar Vision -- standalone analysis worker.

What it does
  Consumes analysis jobs from the Redis queue sv:queue:analyze and runs the
  full pipeline: parse PDF -> concurrent VLM chart analysis -> write result
  cache -> persist history. The API process is then left doing only auth,
  caching, and enqueueing, and uvicorn --reload can no longer cut off an
  analysis that is mid-flight.

Reliability semantics (BRPOPLPUSH queue)
  - A popped payload moves into the processing list and is LREM-acked only on
    a normal finish, so a killed or power-cycled worker cannot lose jobs: they
    stay in processing.
  - reclaim_processing() at startup moves stranded payloads back to the main
    queue and reruns them. Analyses are idempotent: a rerun costs a little API
    quota, nothing else.
  - CTRL+C cancellation deliberately skips the ack (recovered next startup);
    a business-level failure already recorded its reason in the job record and
    is acked -- no pointless retries.

Relation to the fallback path
  - Without Redis the worker exits with an explanatory message and a non-zero
    code. The API meanwhile runs jobs in-process (see submit_analysis_task),
    so the product stays whole. The worker is an enhancement, never a hard
    requirement.

Usage
  python worker.py            # foreground, CTRL+C drains gracefully
  start_worker.bat            # own window (start_server.bat launches it too)
"""

import asyncio
import contextlib
import signal

from app.core.config import settings
from app.core.logging import setup_logging, logger
from app.core.store import store
from app.services import task_manager

POP_TIMEOUT = 5  # 阻塞出队秒数，也是停止检查的心跳间隔


async def _run_one(payload: str, sem: asyncio.Semaphore) -> None:
    """Run one job; ack/cancel policy lives in execute_job_from_payload."""
    try:
        await task_manager.execute_job_from_payload(payload)
    except asyncio.CancelledError:
        logger.warning("任务被中断；未确认出队，重启 worker 时由 processing 回收重跑")
        raise
    finally:
        sem.release()


async def main(stop: asyncio.Event) -> None:
    setup_logging()
    logger.info("🔧 Scholar Vision Worker 启动")

    if not await store.queue_available():
        logger.error(
            f"❌ Redis 不可用（{settings.REDIS_URL}），worker 无事可做。\n"
            "   队列模式需要 Redis：docker compose up -d redis 或本地安装。\n"
            "   （不想用 Redis 就直接跑 API——它会自动退回进程内执行。）"
        )
        raise SystemExit(1)

    reclaimed = await store.reclaim_processing(settings.QUEUE_NAME, settings.PROCESSING_LIST)
    if reclaimed:
        logger.info(f"♻️ 已回收 {reclaimed} 个上次未完成任务，重新入队")

    sem = asyncio.Semaphore(max(1, settings.WORKER_CONCURRENCY))
    inflight: set[asyncio.Task] = set()
    logger.info(f"👂 监听队列 {settings.QUEUE_NAME}，并发上限 {settings.WORKER_CONCURRENCY}")

    try:
        while not stop.is_set():
            # 先拿信号量再出队：保证取出的任务一定有空位执行，
            # 否则任务积压在本进程内存里，崩溃时同样丢失
            try:
                await asyncio.wait_for(sem.acquire(), timeout=POP_TIMEOUT)
            except asyncio.TimeoutError:
                continue

            if stop.is_set():
                sem.release()
                break

            payload = await store.queue_pop(
                settings.QUEUE_NAME, settings.PROCESSING_LIST, timeout=1
            )
            if payload is None:
                sem.release()
                continue

            logger.info("📥 领取任务")
            t = asyncio.create_task(_run_one(payload, sem))
            inflight.add(t)
            t.add_done_callback(inflight.discard)
    finally:
        logger.info(f"🛑 停止消费，等待 {len(inflight)} 个在途任务收尾…")
        if inflight:
            # shield：即使本协程正被取消，也给在途任务一次写状态/确认的机会
            with contextlib.suppress(BaseException):
                await asyncio.shield(
                    asyncio.wait_for(
                        asyncio.gather(*list(inflight), return_exceptions=True),
                        timeout=POP_TIMEOUT + 30,
                    )
                )
        logger.info("Worker 已退出")


if __name__ == "__main__":
    stop_event = asyncio.Event()
    loop = asyncio.new_event_loop()
    exit_code = 0
    # POSIX 下信号直接置位；Windows 的 CTRL+C 走 KeyboardInterrupt 分支
    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", None)):
        if sig is not None:
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, stop_event.set)
    try:
        loop.run_until_complete(main(stop_event))
    except KeyboardInterrupt:
        logger.info("收到 CTRL+C。在途任务未确认，重启 worker 将自动回收；再按一次 CTRL+C 强退")
    except SystemExit as exc:
        # 保留非零退出码（如"Redis 不可用"），别让调用方误以为 worker 正常结束
        exit_code = exc.code if isinstance(exc.code, int) else 1
    finally:
        with contextlib.suppress(Exception):
            loop.run_until_complete(task_manager.shutdown_tasks())
        loop.close()
    raise SystemExit(exit_code)
