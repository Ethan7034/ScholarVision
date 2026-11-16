import arxiv
from app.core.logging import logger

def fetch_arxiv_papers(query: str, max_results: int = 3) -> list:
    """根据关键词从 ArXiv 抓取论文信息"""
    logger.info(f"Fetching arXiv papers for: {query}")
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate
    )
    
    results = []
    for paper in search.results():
        results.append({
            "title": paper.title,
            "summary": paper.summary,
            "pdf_url": paper.pdf_url,
            "published": str(paper.published.date())
        })
    return results