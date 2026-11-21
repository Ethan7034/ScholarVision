import sys
import os

# 强行把上一级目录加入到系统路径中，防止找不到 app 模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.pipelines.llm_client import analyze_chart

if __name__ == "__main__":
    test_image = "../images/page3_img1.png" 
    test_prompt = "You are an academic AI. Analyze this chart: 1. Chart Type 2. Key Data Trends 3. Academic Conclusion."
    
    print("Analyzing chart with VLM (Fallback enabled)...")
    
    # 注意这里！调用的时候传两个参数：图片路径 和 提示词
    result = analyze_chart(test_image, test_prompt)
    
    print("\n=== Final VLM Result ===")
    print(result)