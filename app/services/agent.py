from app.pipelines.parser import extract_pdf_content
from app.pipelines.llm_client import analyze_chart

def orchestrate_analysis(pdf_path: str) -> dict:
    """
    智能体编排层：负责协调解析管道和 AI 模型管道
    """
    # 1. 调度解析层（第 6 层）
    parsed_data = extract_pdf_content(pdf_path)
    
    if not parsed_data.get("images"):
        return {
            "status": "warning",
            "message": "PDF 解析成功，但没有找到任何图片",
            "text_length": len(parsed_data.get("text", ""))
        }
        
    # 2. 调度 AI 模型层（第 5 层）
    first_image = parsed_data["images"][0]
    prompt = "You are an academic AI. Analyze this chart: 1. Chart Type 2. Key Data Trends 3. Academic Conclusion."
    
    ai_analysis = analyze_chart(first_image, prompt)
    
    # 3. 返回最终结构化数据
    return {
        "status": "success",
        "extracted_text_length": len(parsed_data.get("text", "")),
        "analyzed_image": first_image,
        "vlm_result": ai_analysis
    }