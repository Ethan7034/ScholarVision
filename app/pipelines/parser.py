"""
Layer 6 -- Parsing & extraction.

Design notes
  - Parsing runs in a thread pool because PyMuPDF is a synchronous C-extension
    library and must never touch the event loop directly.
  - Output directories are isolated per job. v1.0 wrote every upload into one
    images/ folder as page{n}_img{i}, so two concurrent uploads overwrote
    each other's files; v2.0 gives every job its own subdirectory.
  - Images are deduplicated by xref: v1.0 re-extracted a figure once per
    reference site inside the PDF.
"""

import asyncio
import os

import pymupdf

from app.core.logging import logger


def _extract_sync(pdf_path: str, output_dir: str, max_images: int) -> dict:
    """Synchronous extraction body, executed inside a thread pool."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise ValueError(f"❌ PDF 打开失败: {exc}")

    all_text = ""
    extracted_images: list[str] = []
    seen_xrefs: set[int] = set()

    try:
        for page_num in range(doc.page_count):
            page = doc[page_num]
            all_text += page.get_text()

            for img_index, img in enumerate(page.get_images(full=True)):
                xref = img[0]
                if xref in seen_xrefs:  # 同一图片资源只抽一次
                    continue
                seen_xrefs.add(xref)

                if len(extracted_images) >= max_images:
                    logger.info(f"⚠️ 图片数达上限 {max_images}，其余跳过")
                    return {"text": all_text, "images": extracted_images, "truncated": True}

                try:
                    base_image = doc.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                except Exception as exc:
                    logger.warning(f"跳过无法抽取的图片 xref={xref}: {exc}")
                    continue

                if not image_bytes:
                    continue  # 0 字节鬼图，下游会报错，这里直接丢弃

                image_filename = os.path.join(
                    output_dir, f"page{page_num + 1}_img{img_index + 1}.{image_ext}"
                )
                with open(image_filename, "wb") as f:
                    f.write(image_bytes)
                extracted_images.append(image_filename)
    finally:
        doc.close()

    return {"text": all_text, "images": extracted_images, "truncated": False}


async def extract_pdf_content_async(
    pdf_path: str, output_dir: str = "images", max_images: int = 8
) -> dict:
    """Async wrapper: run the blocking extraction in a worker thread.

    max_images defaults to 8 because every figure costs one VLM call; without
    a cap, a long paper with dozens of figures would blow up both latency and
    API quota.
    """
    return await asyncio.to_thread(_extract_sync, pdf_path, output_dir, max_images)


def extract_pdf_content(pdf_path: str, output_dir: str = "images") -> dict:
    """Synchronous entry kept for tests/test_parser.py and similar scripts."""
    return _extract_sync(pdf_path, output_dir, max_images=10_000)
