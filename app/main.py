"""
Application entry point.

What lives here
  1. SessionGuardMiddleware -- gateway-level session interception
     (unauthenticated page loads get a 302, API calls get a 401).
  2. lifespan -- on shutdown, drain in-flight analysis jobs and close the
     VLM connection pool.
  3. /api/health -- reports the storage backend actually in effect (redis vs
     in-process memory) plus queue depth.
  4. /dashboard -- a protected page that demonstrates the
     "unauthenticated visit -> 302 back to landing" flow end to end.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from app.core.config import settings
from app.core.gateway import SessionGuardMiddleware
from app.core.logging import setup_logging
from app.core.security import get_current_user
from app.core.store import store
from app.pipelines import llm_client
from app.routers import analyze, auth, search
from app.services import task_manager
from fastapi.staticfiles import StaticFiles

setup_logging()

BASE_DIR = Path(__file__).resolve().parent.parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时探测一次存储后端，日志里能直接看到 redis 还是降级内存
    info = store.info()
    app.state.storage_backend = info["backend"]
    yield
    # 关闭时优雅收尾：先停在途任务，再关连接池
    await task_manager.shutdown_tasks()
    await llm_client.shutdown_client()


app = FastAPI(
    title="Scholar Vision",
    description="Multimodal Academic Pipeline (v2.0)",
    lifespan=lifespan,
)

# 中间件：必须在路由注册前后均可，Starlette 会在请求进入路由前执行
app.add_middleware(SessionGuardMiddleware)

# 挂载所有路由
app.include_router(analyze.router, prefix="/api", tags=["Analysis"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(search.router, prefix="/api", tags=["Search"])


@app.get("/api/health")
async def health():
    """Liveness probe: storage backend, queue mode, and queue depth.

    Safe to poll from a tunnel watchdog or an operations dashboard.
    """
    depth = await task_manager.queue_depth()
    return {
        "status": "ok",
        "project": settings.PROJECT_NAME,
        "storage": store.info(),
        "queue": {
            "enabled": depth is not None,
            "pending": depth,
            "name": settings.QUEUE_NAME if depth is not None else None,
        },
    }


@app.get("/")
def serve_frontend():
    return FileResponse(BASE_DIR / "frontend" / "index.html")


@app.get("/dashboard")
def serve_dashboard(request: Request, current_user=Depends(get_current_user)):
    """Protected history page.

    An unauthenticated visit never reaches this handler --
    SessionGuardMiddleware already redirected it to
    "/?auth=required&next=%2Fdashboard". The middleware only verifies the
    signature; this handler additionally confirms the account still exists,
    so a valid signature cannot outlive a deleted user.
    """
    page = BASE_DIR / "frontend" / "dashboard.html"
    if not page.exists():
        return JSONResponse({"detail": "页面尚未部署"}, status_code=404)
    return FileResponse(page)


app.mount("/frontend", StaticFiles(directory=BASE_DIR / "frontend"), name="frontend")
