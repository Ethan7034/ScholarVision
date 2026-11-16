from fastapi import APIRouter, Query
from app.pipelines.scraper import fetch_arxiv_papers

router = APIRouter()

@router.get("/search")
def search_papers(keyword: str = Query(..., min_length=2)):
    """搜索最新的学术论文"""
    papers = fetch_arxiv_papers(keyword)
    return {"status": "success", "results": papers}