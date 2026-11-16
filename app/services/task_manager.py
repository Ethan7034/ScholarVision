from app.core.logging import logger

def process_paper_in_background(file_path: str, filename: str):
    """
    后台任务：模拟复杂的处理管线，后续可接入 Celery/RabbitMQ
    """
    logger.info(f"[Background Task] Started processing: {filename}")
    # 这里原本可以放耗时的 PDF 解析和 VLM 调用
    # 演示用，直接打日志
    logger.info(f"[Background Task] Finished processing: {filename}")