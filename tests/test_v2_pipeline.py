"""
Scholar Vision v2.0 端到端测试

覆盖四条核心断言：
  1. 网关拦截：未登录访问受保护页面 → 302 回主页并带 auth=required
  2. 网关拦截：未登录调用接口 → 401 + login_required
  3. 登录闭环：register → login 拿到 httpOnly Cookie → /auth/me 通过 → logout 后失效
  4. 异步任务：提交立即返回 job_id，轮询拿到真实进度与结果（VLM 已 mock，不烧配额）

注意：测试用临时 sqlite 文件，不碰开发用的 scholar_vision.db；
     VLM 调用被 monkeypatch 替换，不会真实请求 Intern-S2。
"""

import os
import tempfile

# 必须在导入 app 之前设置：database.py 在导入时就会创建 engine
# Windows 绝对路径的 sqlite URL 形式为 sqlite:///C:/x/y.db（三斜杠，不额外补斜杠）
_TMP_DB = os.path.join(tempfile.mkdtemp(), "test.db").replace(os.sep, "/")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["SECRET_KEY"] = "test-secret-key-only-for-pytest"
os.environ["INTERN_API_KEY"] = "dummy"

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import task_manager


@pytest.fixture()
def client():
    # 不自动跟随重定向，才能断言 302 与 Location
    with TestClient(app, follow_redirects=False) as c:
        yield c


def _register_and_login(client, username):
    r = client.post("/auth/register", json={"username": username, "password": "***"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/login", json={"username": username, "password": "***"})
    assert r.status_code == 200, r.text
    set_cookie = r.headers.get("set-cookie", "")
    assert "sv_session=" in set_cookie
    assert "httponly" in set_cookie.lower()  # 关键：token 不能被 JS 读取
    return set_cookie


# ---------------------------------------------------------------- 1/2. 网关
def test_dashboard_requires_login_and_redirects(client):
    r = client.get("/dashboard", headers={"accept": "text/html"})
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/?auth=required")
    assert "next=" in loc  # 登录后可回到原目标


def test_api_returns_401_not_redirect(client):
    r = client.get("/api/tasks/whatever")
    assert r.status_code == 401
    body = r.json()
    assert body["login_required"] is True


def test_public_paths_stay_open(client):
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    # 登录接口本身必须可匿名访问，否则永远无法登录
    assert client.post("/auth/login", json={"username": "x", "password": "***"}).status_code == 400


def test_tampered_token_is_rejected(client):
    r = client.get("/dashboard", headers={"accept": "text/html", "cookie": "sv_session=garbage.token.here"})
    assert r.status_code == 302  # 伪造 token 仍视为未登录


# ---------------------------------------------------------------- 3. 会话闭环
def test_session_lifecycle(client):
    cookie = _register_and_login(client, "alice")

    r = client.get("/auth/me", headers={"cookie": cookie})
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    r = client.get("/dashboard", headers={"accept": "text/html", "cookie": cookie})
    assert r.status_code == 200

    # 登出后 Cookie 失效
    logout = client.post("/auth/logout", headers={"cookie": cookie})
    assert logout.status_code == 200
    assert client.get("/auth/me", headers={"cookie": cookie}).status_code == 401

    # 重复注册同名用户应被拒
    assert client.post("/auth/register", json={"username": "alice", "password": "***"}).status_code == 400


# ---------------------------------------------------------------- 4. 异步任务
def test_analyze_is_async_and_reports_progress(client, monkeypatch):
    cookie = _register_and_login(client, "bob")

    # mock 编排层：不真的调用 VLM，直接返回可控结果并推进进度
    # （v2.1：进度回调改为协程，必须 await，与真实编排层调用方式一致）
    async def fake_orchestrate(pdf_path, output_dir="images", prompt=None, progress_cb=None):
        if progress_cb:
            await progress_cb(1, 2)
            await progress_cb(2, 2)
        return {
            "status": "success",
            "extracted_text_length": 1234,
            "analyzed_image": "images/x/page1_img1.png",
            "images_total": 2,
            "images_ok": 2,
            "vlm_result": "## fake\n\nmocked analysis",
            "analyses": [],
        }

    monkeypatch.setattr(task_manager, "orchestrate_analysis_async", fake_orchestrate)

    pdf_bytes = b"%PDF-1.4 fake content for test"
    r = client.post(
        "/api/analyze",
        files={"file": ("paper.pdf", pdf_bytes, "application/pdf")},
        headers={"cookie": cookie},
    )
    assert r.status_code == 202, r.text
    submit = r.json()
    assert submit["job_id"], "提交后必须拿到 job_id"
    assert submit["status"] in ("queued", "completed")

    # 轮询直到任务终态
    import time

    job = None
    for _ in range(50):
        rr = client.get(f"/api/tasks/{submit['job_id']}", headers={"cookie": cookie})
        assert rr.status_code == 200
        job = rr.json()
        if job["status"] in ("completed", "failed", "cancelled"):
            break
        time.sleep(0.1)

    assert job and job["status"] == "completed", job
    assert job["result"]["images_ok"] == 2
    assert job["progress"]["done"] == 2


def test_analyze_rejects_non_pdf(client):
    cookie = _register_and_login(client, "carol")
    r = client.post(
        "/api/analyze",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers={"cookie": cookie},
    )
    assert r.status_code == 400


def test_upload_filename_cannot_traverse(client):
    cookie = _register_and_login(client, "dave")
    # 恶意文件名不能跳出上传目录
    assert ".." not in task_manager.sanitize_filename("../../../evil.pdf")
    assert "/" not in task_manager.sanitize_filename("a/b/c.pdf")
    assert task_manager.sanitize_filename("").endswith("pdf")


def test_cache_hit_skips_pipeline(client, monkeypatch):
    cookie = _register_and_login(client, "erin")

    async def fake_orchestrate(pdf_path, output_dir="images", prompt=None, progress_cb=None):
        return {
            "status": "success",
            "extracted_text_length": 10,
            "analyzed_image": "images/y/page1_img1.png",
            "images_total": 1,
            "images_ok": 1,
            "vlm_result": "first",
            "analyses": [],
        }

    monkeypatch.setattr(task_manager, "orchestrate_analysis_async", fake_orchestrate)

    pdf = b"%PDF-1.4 the same bytes twice"
    import hashlib
    import asyncio
    from app.core.store import analyze_key, store

    file_hash = hashlib.md5(pdf).hexdigest()
    first = client.post(
        "/api/analyze", files={"file": ("p.pdf", pdf, "application/pdf")}, headers={"cookie": cookie}
    )
    assert first.status_code == 202

    # 直接把结果写进缓存，模拟"第二次上传同一份 PDF"
    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        store.set_json(
            analyze_key(file_hash),
            {"status": "success", "extracted_text_length": 10, "analyzed_image": "a.png",
             "images_total": 1, "images_ok": 1, "vlm_result": "from-cache", "analyses": []},
            ttl=60,
        )
    )
    loop.close()

    second = client.post(
        "/api/analyze", files={"file": ("p.pdf", pdf, "application/pdf")}, headers={"cookie": cookie}
    )
    assert second.status_code == 202
    data = second.json()
    assert data["cached"] is True
    assert data["job_id"] is None
    assert data["result"]["vlm_result"] == "from-cache"
