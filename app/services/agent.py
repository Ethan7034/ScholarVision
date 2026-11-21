"""
Layer 4 -- Agent Orchestration.

What v1.0 did wrong
  orchestrate_analysis was synchronous and analyzed only
  parsed_data["images"][0]; every other extracted chart was parsed for
  nothing.

v2.0 design
  - Fully asynchronous: parse -> concurrent VLM calls -> aggregate.
  - A semaphore (settings.MAX_CONCURRENT_ANALYSIS) caps concurrent requests,
    so a long paper with a dozen figures cannot burst the model API quota.
  - progress_cb(done, total) lets the job layer persist real progress that the
    frontend polls for; no simulated animations anywhere.
  - One failed chart never sinks the job: failures are recorded per image
    while successful charts return normally.
"""

import asyncio
import os

from app.core.config import settings
from app.core.logging import logger
from app.pipelines.llm_client import DEFAULT_PROMPT, analyze_chart_async
from app.pipelines.parser import extract_pdf_content_async


def _basename(path: str) -> str:
    return path.replace("\\", "/").split("/")[-1]


async def orchestrate_analysis_async(
    pdf_path: str,
    output_dir: str = "images",
    prompt: str = DEFAULT_PROMPT,
    progress_cb=None,
) -> dict:
    """Run one complete paper analysis: parse, analyze every chart, aggregate.

    Returns status: success / warning / error.
    """
    # 1. 调度解析层（线程池，不阻塞事件循环）
    parsed_data = await extract_pdf_content_async(pdf_path, output_dir=output_dir)

    images = parsed_data.get("images", [])
    if not images:
        return {
            "status": "warning",
            "message": "PDF 解析成功，但没有找到任何图片",
            "text_length": len(parsed_data.get("text", "")),
        }

    total = len(images)
    logger.info(f"🧠 编排 {total} 张图表，并发上限 {settings.MAX_CONCURRENT_ANALYSIS}")

    # 2. 并发调度 AI 层，信号量控制同时打到 VLM 的请求数
    semaphore = asyncio.Semaphore(max(1, settings.MAX_CONCURRENT_ANALYSIS))
    state = {"done": 0}
    count_lock = asyncio.Lock()

    async def _analyze_one(image_path: str) -> dict:
        async with semaphore:
            result = await analyze_chart_async(image_path, prompt)

        async with count_lock:
            state["done"] += 1
            if progress_cb:
                try:
                    outcome = progress_cb(state["done"], total)
                    # 跨进程模式下回调是协程（要写 Redis），必须 await；
                    # 同步回调返回 None 时跳过
                    if asyncio.iscoroutine(outcome):
                        await outcome
                except Exception:
                    pass  # 进度写缓存失败不影响分析本体

        if result["ok"]:
            return {"image": image_path, "result": result["content"]}
        return {"image": image_path, "error": result["error"]}

    analyses = list(await asyncio.gather(*(_analyze_one(p) for p in images)))

    ok_items = [a for a in analyses if "result" in a]
    if not ok_items:
        return {
            "status": "error",
            "message": "所有图表分析均失败",
            "analyses": analyses,
        }

    # 3. 汇总为 Markdown，保持前端 marked.parse 渲染兼容
    summary_parts = [
        f"### 📊 {_basename(item['image'])}\n\n{item['result']}" for item in ok_items
    ]

    return {
        "status": "success",
        "extracted_text_length": len(parsed_data.get("text", "")),
        "analyzed_image": ok_items[0]["image"],
        "images_total": total,
        "images_ok": len(ok_items),
        "vlm_result": "\n\n---\n\n".join(summary_parts),
        "analyses": analyses,
    }


# 旧接口名保底：给可能残留的同步调用方一个明确报错，而不是静默走阻塞路径
def orchestrate_analysis(pdf_path: str, *args, **kwargs) -> dict:
    raise RuntimeError(
        "orchestrate_analysis 已升级为异步版本，请改用 "
        "await orchestrate_analysis_async(...)（v2.0 事件循环改造）"
    )
