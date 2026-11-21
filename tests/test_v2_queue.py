"""
v2.0 队列双模测试：Redis 可用走外部队列，不可用退回进程内执行

本机没有 Redis 也能跑：队列方法用 monkeypatch 模拟，
执行体走真实代码路径（含 uploads 写盘、ack、临时文件清理）。
真实 Redis + worker 进程的端到端联调见 README"已验证"一节。
"""

import asyncio
import json
import os
import tempfile

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db").replace(os.sep, "/"),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key-only-for-pytest")
os.environ.setdefault("INTERN_API_KEY", "dummy")

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.store import KVStore
from app.main import app
from app.services import task_manager

PDF = b"%PDF-1.4 queue mode test bytes"


@pytest.fixture()
def client():
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _login(client, name):
    client.post("/auth/register", json={"username": name, "password": "***"})
    return client.post(
        "/auth/login", json={"username": name, "password": "***"}
    ).headers.get("set-cookie", "").split(";")[0]


def _fake_orchestrate(result=None):
    async def fake(pdf_path, output_dir="images", prompt=None, progress_cb=None):
        if progress_cb:
            await progress_cb(1, 1)  # v2.1：异步回调必须被 await 才生效
        return result or {
            "status": "success",
            "extracted_text_length": 5,
            "analyzed_image": "images/z/page1_img1.png",
            "images_total": 1,
            "images_ok": 1,
            "vlm_result": "queued-ok",
            "analyses": [],
        }
    return fake


# ---------------------------------------------------------------- 队列模式
def test_health_reports_queue_disabled_without_redis(client):
    body = client.get("/api/health").json()
    assert body["queue"]["enabled"] is False  # 本机无 Redis → 进程内模式


def test_submit_enqueues_instead_of_inprocess(client, monkeypatch):
    cookie = _login(client, "q_user")

    pushed, acked = [], []

    async def fake_avail(self): return True
    async def fake_push(self, queue, payload):
        pushed.append((queue, payload)); return True
    async def fake_ack(self, processing, payload): acked.append(payload)

    monkeypatch.setattr(KVStore, "queue_available", fake_avail)
    monkeypatch.setattr(KVStore, "queue_push", fake_push)
    monkeypatch.setattr(KVStore, "queue_ack", fake_ack)

    r = client.post(
        "/api/analyze", files={"file": ("q.pdf", PDF, "application/pdf")},
        headers={"cookie": cookie},
    )
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    # 关键断言 1：payload 进了队列，且没有创建进程内任务
    assert len(pushed) == 1
    queue_name, payload = pushed[0]
    assert queue_name == settings.QUEUE_NAME
    spec = json.loads(payload)
    assert spec["job_id"] == job_id
    assert job_id not in task_manager._INPROCESS

    # 关键断言 2：任务状态是 queued，PDF 文件留在 uploads 等待外部 worker
    job = asyncio.run(task_manager.get_task_status(job_id))
    assert job["status"] == "queued"
    assert os.path.exists(spec["pdf_path"])

    # 模拟 worker 消费这条 payload（执行体是真实代码，编排被 mock）
    monkeypatch.setattr(
        task_manager, "orchestrate_analysis_async", _fake_orchestrate()
    )
    asyncio.run(task_manager.execute_job_from_payload(payload))

    # 关键断言 3：完成 → ack 出 processing、状态 completed、进度持久化、临时文件清理
    assert acked == [payload]
    job = asyncio.run(task_manager.get_task_status(job_id))
    assert job["status"] == "completed"
    assert job["result"]["vlm_result"] == "queued-ok"
    assert job["progress"] == {"done": 1, "total": 1}
    assert not os.path.exists(spec["pdf_path"])


def test_queue_push_failure_falls_back_inprocess(client, monkeypatch):
    """Redis 半路故障（探测 OK 但 push 抛错）时不能让上传 500，必须兜底执行。"""
    cookie = _login(client, "fb_user")

    async def fake_avail(self): return True
    async def boom_push(self, queue, payload): raise ConnectionError("redis gone")
    monkeypatch.setattr(KVStore, "queue_available", fake_avail)
    monkeypatch.setattr(KVStore, "queue_push", boom_push)
    monkeypatch.setattr(
        task_manager, "orchestrate_analysis_async", _fake_orchestrate()
    )

    # 必须用独立字节：test 1 已把 PDF 的 MD5 写进分析缓存，
    # 同字节上传会直接缓存命中（job_id=None），根本走不到入队/兜底分支
    unique_pdf = PDF + b" fallback-path-only"
    r = client.post(
        "/api/analyze", files={"file": ("fb.pdf", unique_pdf, "application/pdf")},
        headers={"cookie": cookie},
    )
    assert r.status_code == 202  # 没炸
    job_id = r.json()["job_id"]
    assert job_id is not None, "缓存命中说明字节撞车了，此测试应走队列/兜底路径"
    job = None
    for _ in range(50):
        job = asyncio.run(task_manager.get_task_status(job_id))
        if job and job["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "completed"  # 兜底路径真实执行完了


# ---------------------------------------------------------------- 进度通道
def test_async_progress_callback_persisted(client, monkeypatch):
    """
    worker 模式没有内存 _PROGRESS 合并，进度完全依赖回调写 job 记录。
    这里断言：编排层收到的 progress_cb 是协程、await 后状态实时可读。
    """
    spy = {}

    async def spy_orch(pdf_path, output_dir="images", prompt=None, progress_cb=None):
        spy["cb"] = progress_cb
        assert asyncio.iscoroutinefunction(progress_cb), "回调必须是协程"
        await progress_cb(2, 3)
        # 回调返回后立刻在同一事件循环里读，进度应已持久化（跨进程可见的通道）
        job = await task_manager.get_task_status("cb-job")
        assert job["progress"] == {"done": 2, "total": 3}
        return {
            "status": "success",
            "extracted_text_length": 1,
            "analyzed_image": "x",
            "images_total": 3,
            "images_ok": 3,
            "vlm_result": "p",
            "analyses": [],
        }

    monkeypatch.setattr(task_manager, "orchestrate_analysis_async", spy_orch)

    os.makedirs("uploads", exist_ok=True)
    pdf = os.path.join("uploads", "cb_tmp.pdf")
    with open(pdf, "wb") as f:
        f.write(b"x")

    async def run():
        await task_manager.execute_job(
            "cb-job", pdf, "cb.pdf", "cb-hash", os.path.join("images", "cb-tmp")
        )

    asyncio.run(run())
    assert "cb" in spy
    job = asyncio.run(task_manager.get_task_status("cb-job"))
    assert job["status"] == "completed"
    assert job["progress"] == {"done": 3, "total": 3}
    assert not os.path.exists(pdf)


def test_reclaim_moves_processing_back(client, monkeypatch):
    """worker 崩溃场景：processing 里的 payload 应被挪回主队列。"""
    moved = []

    class FakeClient:
        async def rpoplpush(self, src, dst):
            if not moved:
                moved.append("task-1")
                return "task-1"
            return None

    store = task_manager.store
    monkeypatch.setattr(store, "_get_client", lambda: _ret(FakeClient()))

    n = asyncio.run(store.reclaim_processing("q", "proc"))
    assert n == 1


def _ret(v):
    async def f(): return v
    return f()


# ---------------------------------------------------------------- 真实命令形态
def test_store_queue_methods_against_real_redis_commands(monkeypatch):
    """
    用 fakeredis（内存实现的 Redis 协议语义）验证 KVStore 队列方法真的
    按 LPUSH/BRPOPLPUSH/LREM/RPOPLPUSH 工作。
    覆盖的是"我们对 redis-py 的调用形态对不对"——纯 mock 测试覆盖不到这层，
    真实 Redis server 联调留给启用 Redis 后的部署验证。
    """
    from fakeredis.aioredis import FakeRedis

    from app.core.store import KVStore

    fa = FakeRedis(decode_responses=True)
    st = KVStore("redis://fake:6379/0")
    st._client = fa
    st._tried = True
    st.backend = "redis"

    async def flow():
        assert await st.queue_available() is True

        await st.queue_push("q", "job-a")
        await st.queue_push("q", "job-b")
        assert await st.queue_len("q") == 2

        # BRPOPLPUSH：右端弹出（LPUSH 左端压入 → 先入队先出，FIFO）
        got = await st.queue_pop("q", "proc", timeout=1)
        assert got == "job-a", f"FIFO 顺序应为 job-a，实际 {got}"
        assert await st.queue_len("q") == 1
        assert await st.queue_len("proc") == 1

        # 执行完成 → ack 出 processing
        await st.queue_ack("proc", "job-a")
        assert await st.queue_len("proc") == 0

        # 模拟 job-b 执行中 worker 崩溃：不 ack，任务滞留 processing
        got2 = await st.queue_pop("q", "proc", timeout=1)
        assert got2 == "job-b"
        assert await st.queue_len("proc") == 1

        # 重启回收：processing 挪回主队列
        moved = await st.reclaim_processing("q", "proc")
        assert moved == 1
        assert await st.queue_len("proc") == 0
        assert await st.queue_len("q") == 1

    asyncio.run(flow())
