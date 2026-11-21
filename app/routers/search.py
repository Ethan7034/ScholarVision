"""
Search route with Redis-backed result caching.

The arxiv client is a synchronous, blocking library (urllib underneath). v2.0
pushes it off the event loop with asyncio.to_thread and caches results per
keyword for ten minutes, cutting repeated hits against the upstream site.
"""

import asyncio

from fastapi import APIRouter, Depends, Query

from app.core.config import settings
from app.core.logging import logger
from app.core.security import get_current_user
from app.core.store import search_key, store
from app.pipelines.scraper import fetch_arxiv_papers

router = APIRouter()


@router.get("/search")
async def search_papers(
    keyword: str = Query(..., min_length=2),
    _user=Depends(get_current_user),
):
    """Search recent arXiv papers, cache-first."""
    cache_key = search_key(keyword)
    cached = await store.get_json(cache_key)
    if cached is not None:
        logger.info(f"🎯 搜索缓存命中: {keyword}")
        return {"status": "success", "results": cached, "cached": True}

    # arxiv 库是同步阻塞的，放线程池里跑，不卡事件循环
    papers = await asyncio.to_thread(fetch_arxiv_papers, keyword)
    if papers:
        await store.set_json(cache_key, papers, ttl=settings.CACHE_TTL_SEARCH)

    return {"status": "success", "results": papers, "cached": False}
