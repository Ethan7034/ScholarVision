from fastapi import FastAPI
from app.core.config import settings
from app.routers import analyze 
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import analyze, auth, search
from app.core.logging import setup_logging

setup_logging()
app = FastAPI(title="Scholar Vision", description="Multimodal Academic Pipeline")

# 挂载所有路由
app.include_router(analyze.router, prefix="/api", tags=["Analysis"])
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(search.router, prefix="/api", tags=["Search"])

@app.get("/")
def serve_frontend():
    return FileResponse("frontend/index.html")

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")