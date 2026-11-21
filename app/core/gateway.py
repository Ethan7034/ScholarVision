"""
Layer 2 -- Security & gateway: session guard middleware.

Product behavior this implements:
  "If a visitor is not logged in, send them back to the landing page and pop
   the SYSTEM_AUTH login dialog."

Implementation (server-side 302 redirect)
  - Browser navigation (page loads, static assets) without a session gets a
    302 back to "/" carrying ?auth=required&next=<original path>; the SPA
    reads that query string and opens SYSTEM_AUTH automatically.
  - API calls (/api/*) without a session get a plain 401 JSON response.
    Redirecting an API call to an HTML page would hand fetch a wall of HTML
    and turn a clean authorization failure into a confusing JSON parse error.

Public allowlist (reachable without a session)
  The landing page "/", /auth/* (register and login must stay anonymous),
  /api/health, and /frontend/* assets -- otherwise a logged-out visitor could
  not even load the login form.
"""

from urllib.parse import quote

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.core.logging import logger
from app.core.security import authenticate_token, extract_token

PUBLIC_EXACT = {"/", "/favicon.ico", "/api/health", "/docs", "/redoc", "/openapi.json"}
PUBLIC_PREFIX = ("/auth/", "/frontend/", "/static/", "/assets/")
API_PREFIX = ("/api/",)


def _is_api_request(request) -> bool:
    """Decide 401 versus 302 by telling API calls apart from page loads."""
    if request.url.path.startswith(API_PREFIX):
        return True
    if request.headers.get("x-requested-with", "").lower() == "xmlhttprequest":
        return True
    # 浏览器地址栏直接输入/刷新页面时 Accept 必含 text/html
    return "text/html" not in request.headers.get("accept", "")


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in PUBLIC_PREFIX)


class SessionGuardMiddleware(BaseHTTPMiddleware):
    """Gateway session guard: protected requests must present a valid session."""

    async def dispatch(self, request, call_next) -> Response:
        path = request.url.path

        if _is_public(path):
            return await call_next(request)

        token = extract_token(request)
        username = await authenticate_token(token)

        if username:
            request.state.username = username
            return await call_next(request)

        logger.info(f"🔒 未授权访问被拦截: {request.method} {path}")
        if _is_api_request(request):
            return JSONResponse(
                status_code=401,
                content={
                    "status": "error",
                    "detail": "未登录或会话已过期",
                    "login_required": True,
                },
            )

        query = f"?{request.url.query}" if request.url.query else ""
        next_target = quote(f"{path}{query}", safe="")
        return RedirectResponse(
            url=f"/?auth=required&next={next_target}",
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )
