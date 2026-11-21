"""
Layer 5 -- AI & VLM processing.

What v1.0 did wrong
  analyze_chart called synchronous requests.post(timeout=420) from inside an
  async route. That blocks uvicorn's event loop for the entire wait: for up
  to 420 seconds the server stops answering every other user. This was not
  "slow" -- it froze the whole site per request.

v2.0 design
  - httpx.AsyncClient: the event loop keeps serving other requests while
    awaiting the model.
  - A shared client reuses one TLS connection pool instead of a fresh
    handshake per call.
  - Timeout split into connect / read / write / pool with clear semantics.
  - Failures come back as structured results; error text no longer masquerades
    as normal output.

Call chain: analyze.py -> agent.orchestrate_analysis_async -> parse_pdf ->
analyze_chart_async
"""

import asyncio
import base64
import io
import os

import httpx
from PIL import Image

from app.core.config import settings
from app.core.logging import logger

API_URL = "https://discovery-api.intern-ai.org.cn/v1/chat/completions"
MODEL_NAME = "intern-s2"

# 单次 VLM 调用超时：连接 10s，读取 240s
_TIMEOUT = httpx.Timeout(connect=10.0, read=240.0, write=30.0, pool=10.0)

# 模块级共享客户端（懒创建），复用连接池
_client: httpx.AsyncClient | None = None

DEFAULT_PROMPT = (
    "You are an academic AI. Analyze this chart: "
    "1. Chart Type 2. Key Data Trends 3. Academic Conclusion."
)


def _encode_image(image_path: str, max_size: int = 1024) -> tuple[str, str]:
    """Read, downscale, normalize to JPEG; return (base64, mime).

    Raises ValueError when the file is missing or empty.
    """
    if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
        raise ValueError(f"图片缺失或为 0 字节: {image_path}")

    with Image.open(image_path) as img:
        img.load()
        if img.width > max_size or img.height > max_size:
            ratio = min(max_size / img.width, max_size / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:  # 兼容旧版 Pillow
                resample = Image.LANCZOS
            img = img.resize(new_size, resample)
        rgb_img = img.convert("RGB")

    buffered = io.BytesIO()
    rgb_img.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode("utf-8"), "image/jpeg"


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=_TIMEOUT)
    return _client


async def shutdown_client() -> None:
    """Release the connection pool; called from the lifespan shutdown hook."""
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
        _client = None


async def analyze_chart_async(image_path: str, prompt: str = DEFAULT_PROMPT) -> dict:
    """Send one academic chart to the VLM for analysis.

    Returns {"ok": bool, "content": str | None, "error": str | None}. The
    structured result replaces v1.0's habit of returning error strings as if
    they were analysis output.
    """
    api_key = os.getenv("INTERN_API_KEY") or settings.INTERN_API_KEY
    if not api_key:
        return {"ok": False, "content": None, "error": "INTERN_API_KEY 未配置"}

    try:
        base64_image, mime_type = _encode_image(image_path)
    except Exception as exc:
        logger.error(f"图片预处理失败 {image_path}: {type(exc).__name__} - {exc}")
        return {"ok": False, "content": None, "error": f"图片预处理失败: {exc}"}

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{base64_image}"},
                    },
                ],
            }
        ],
        "temperature": 0.3,
    }

    try:
        client = await _get_client()
        logger.info(f"🔄 提交图表至 VLM: {os.path.basename(image_path)}")
        resp = await client.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()
        return {"ok": True, "content": content, "error": None}
    except httpx.HTTPStatusError as exc:
        logger.error(f"VLM 返回非 2xx: {exc.response.status_code}")
        return {
            "ok": False,
            "content": None,
            "error": f"模型服务返回 {exc.response.status_code}",
        }
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.error(f"VLM 网络异常: {type(exc).__name__}")
        return {"ok": False, "content": None, "error": f"网络异常: {type(exc).__name__}"}
    except Exception as exc:
        logger.error(f"VLM 调用未知异常: {type(exc).__name__} - {exc}")
        return {"ok": False, "content": None, "error": str(exc)}


# 保留同步入口给旧测试脚本使用，内部用 asyncio.run 包一层
def analyze_chart(image_path: str, prompt: str = DEFAULT_PROMPT) -> str:
    result = asyncio.run(analyze_chart_async(image_path, prompt))
    return result["content"] if result["ok"] else f"❌ {result['error']}"


if __name__ == "__main__":
    print(asyncio.run(analyze_chart_async("images/page3_img1.png", DEFAULT_PROMPT)))
