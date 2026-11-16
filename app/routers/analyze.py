from fastapi import APIRouter, HTTPException, UploadFile, File
import os
import shutil
import hashlib
from app.services.agent import orchestrate_analysis
from app.models.schemas import AnalysisResponse, WarningResponse # 👈 引入刚定义的模型

router = APIRouter()

# 🚀 极客操作：内存级缓存（模拟 Redis）
CACHE = {}

@router.post("/analyze", response_model=AnalysisResponse | WarningResponse) # 👈 锁死返回格式
async def analyze_paper(file: UploadFile = File(...)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="❌ 只支持上传 PDF 文件")

    # 读取文件内容，计算 MD5 哈希值（相当于文件的身份证）
    file_content = await file.read()
    file_hash = hashlib.md5(file_content).hexdigest()

    # 查缓存：如果这个文件之前传过，直接返回结果
    if file_hash in CACHE:
        print("🎯 Cache Hit! 直接从内存返回结果，不调用大模型！")
        return CACHE[file_hash]

    temp_file_path = f"temp_{file.filename}"
    try:
        with open(temp_file_path, "wb") as buffer:
            buffer.write(file_content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ 文件保存失败: {e}")

    try:
        # 第一次见这个文件，走真实解析流程
        result = orchestrate_analysis(temp_file_path)
        
        # 把结果存入缓存
        if result["status"] == "success":
            # 加上 filename 字段，匹配 schemas
            result["filename"] = file.filename
            CACHE[file_hash] = result
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)