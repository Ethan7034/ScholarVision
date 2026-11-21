"""
Scraper for arXiv paper metadata.

Bug this fixes
  search.results() was the arxiv 3.x idiom; the installed library is 4.1.0,
  where Search objects no longer expose results() and iteration must go
  through arxiv.Client(). Before the fix /api/search answered 500 with
  "AttributeError: 'Search' object has no attribute 'results'". The bug
  survived v1.0 entirely because the search route was never covered by a
  backend test.
"""

import arxiv
from app.core.logging import logger


def fetch_arxiv_papers(query: str, max_results: int = 3) -> list:
    """Fetch papers matching a keyword, newest first (arxiv 3.x / 4.x safe)."""
    logger.info(f"Fetching arXiv papers for: {query}")
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
    )

    # 4.x: Client().results(search)；3.x: search.results()
    if hasattr(arxiv, "Client"):
        iterator = arxiv.Client().results(search)
    else:  # pragma: no cover - 旧版本兜底
        iterator = search.results()

    results = []
    for paper in iterator:
        results.append(
            {
                "title": paper.title,
                "summary": paper.summary,
                "pdf_url": paper.pdf_url,
                "published": str(paper.published.date()),
            }
        )
    return results
