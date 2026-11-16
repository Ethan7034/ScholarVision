import requests
import os
import base64
import io
import traceback
from PIL import Image # 引入图像处理库
from dotenv import load_dotenv

load_dotenv()

def analyze_chart(image_path: str, prompt: str) -> str:
    api_key = os.getenv("INTERN_API_KEY")
    if not api_key:
        return "❌ INTERN_API_KEY is not set."

    url = "https://discovery-api.intern-ai.org.cn/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


    # 1. 核心升级：读取、压缩图片，并动态识别格式
    import traceback
    try:
        # 检查文件是否为空（防止 PyMuPDF 切出 0 字节的鬼图）
        if not os.path.exists(image_path) or os.path.getsize(image_path) == 0:
            return f"❌ Image Process Error: File is missing or empty (0 bytes) -> {image_path}"

        with Image.open(image_path) as img:
            # 强制加载图片数据，防止有些图片头损坏
            img.load() 
        
            max_size = 1024
            if img.width > max_size or img.height > max_size:
                ratio = min(max_size / img.width, max_size / img.height)
                new_size = (int(img.width * ratio), int(img.height * ratio))
            
                # 兼容新旧版本的 Pillow
                try:
                    resample_filter = Image.Resampling.LANCZOS
                except AttributeError:
                    resample_filter = Image.LANCZOS
                
                img = img.resize(new_size, resample_filter)

            # 统一转为 RGB 模式（去除透明通道，防止存 JPEG 报错）
            rgb_img = img.convert('RGB')
        
            buffered = io.BytesIO()
            rgb_img.save(buffered, format="JPEG", quality=85)
            base64_image = base64.b64encode(buffered.getvalue()).decode('utf-8')
            mime_type = "image/jpeg"
        
    except Exception as e:
        traceback.print_exc() 
        return f"❌ Image Process Error: {type(e).__name__} - {e}"
    
    # 2. 构建 Payload
    payload = {
        "model": "intern-s2",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}}
                ]
            }
        ],
        "temperature": 0.3
    }

    # 3. 发送请求 (把 timeout 直接拉到 420 秒，给大模型一点面子)
    try:
        print(f"🔄 Sending compressed image to Intern-S2...")
        response = requests.post(url, headers=headers, json=payload, timeout=420)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return f"❌ API/Network Error: {e}"

if __name__ == "__main__":
    test_image = "images/page3_img1.png" # 确保路径对
    test_prompt = "Analyze this chart: 1. Chart Type 2. Key Data Trends 3. Academic Conclusion."
    print(analyze_chart(test_image, test_prompt))